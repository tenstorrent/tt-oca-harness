# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS clock-observer UVM agent.

For each ``COUNT_EDGES`` transaction, the driver waits a configurable number
of ``clk_ref_i`` rising edges and concurrently counts edges on each of the
three SMC clocks (ref / smc / periph) plus one DUT-generated gated clock.

IMPORTANT: ``clk_ref_i`` / ``clk_smc_i`` / ``clk_periph_i`` are DUT *inputs*
that ``smc_base_test._bring_up`` drives with cocotb ``Clock(...)``. Their
counts measure the TB clock generators and can never fail because of DUT RTL,
so the scoreboard books them as a **SETUP self-check**, not DUT evidence. The
DUT-side leg is ``gated_clk_probe`` / ``gated_cg_en_probe`` (a passive tb_top
read of a clock-gater output and its enable), which a sequence turns into a
real check via ``expect_gated_clk_running`` / ``expect_gated_cg_en``.

This is a pure observation agent (no DUT drives).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Event, First, RisingEdge
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequencer,
)

from .smc_clk_item import SmcClkItem, SmcClkOp


class SmcClkDriver(uvm_driver):
    """Counts clock rising edges over the requested window."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.dut = None

    async def run_phase(self) -> None:
        self.dut = cocotb.top
        await self.cfg.reset_done.wait()
        self.logger.info("SMC clock observer driver ready")
        while True:
            item = await self.seq_item_port.get_next_item()
            if item.op is SmcClkOp.COUNT_EDGES:
                await self._count(item)
            else:
                raise ValueError(f"unsupported SmcClkOp: {item.op}")
            self.ap.write(item)
            self.seq_item_port.item_done()

    async def _count(self, item: SmcClkItem) -> None:
        dut = self.dut
        stop = Event("clk_count_stop")
        ref_count = [0]
        smc_count = [0]
        periph_count = [0]

        async def _count_one(sig, store):
            while True:
                edge = RisingEdge(sig)
                done = stop.wait()
                ev = await First(edge, done)
                if ev is done:
                    return
                store[0] += 1

        ref_task = cocotb.start_soon(_count_one(dut.clk_ref_i, ref_count))
        smc_task = cocotb.start_soon(_count_one(dut.clk_smc_i, smc_count))
        periph_task = cocotb.start_soon(_count_one(dut.clk_periph_i, periph_count))

        # DUT-generated gated clock over the same window. Passive read only, and
        # the only leg of this item that can fail because of DUT RTL -- the three
        # counts above are TB-driven inputs (see SmcClkItem).
        gated_count = [0]
        gated_task = None
        gated_sig = getattr(dut, item.gated_clk_probe, None)
        if gated_sig is not None:
            gated_task = cocotb.start_soon(_count_one(gated_sig, gated_count))

        # The window is window_ref_cycles clk_ref_i edges, the same edges
        # ref_count tallies.
        for _ in range(item.window_ref_cycles):
            await RisingEdge(dut.clk_ref_i)
        stop.set()
        await ref_task
        await smc_task
        await periph_task

        item.ref_rising_edges = ref_count[0]
        item.smc_rising_edges = smc_count[0]
        item.periph_rising_edges = periph_count[0]
        if gated_task is not None:
            await gated_task
            item.gated_clk_rising_edges = gated_count[0]
            en_sig = getattr(dut, item.gated_cg_en_probe, None)
            en_val = None if en_sig is None else en_sig.value
            item.gated_cg_en = int(en_val) if en_val is not None and en_val.is_resolvable else -1
            item.gated_probe_resolvable = item.gated_cg_en >= 0
        self.logger.info("Counted %s", item)


class SmcClkAgent(uvm_agent):
    """SMC OSS clock observer agent."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcClkDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
