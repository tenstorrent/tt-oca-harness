# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS reset UVM agent (mixed observation + stimulus)."""

from __future__ import annotations

import cocotb
from pyuvm import (
    ConfigDB,
    uvm_agent,
    uvm_analysis_port,
    uvm_driver,
    uvm_sequencer,
)

from .smc_reset_item import SmcResetItem, SmcResetOp


class SmcResetDriver(uvm_driver):
    """Samples / drives SMC OSS reset and powergood top-level pins."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.ap = uvm_analysis_port("ap", self)
        self.dut = None

    async def run_phase(self) -> None:
        self.dut = cocotb.top
        await self.cfg.reset_done.wait()
        self.logger.info("SMC reset agent driver ready")

        while True:
            item = await self.seq_item_port.get_next_item()
            if item.op is SmcResetOp.SAMPLE or item.op is SmcResetOp.RAW_SAMPLE:
                self._sample(item)
            elif item.op is SmcResetOp.POWERGOOD_LO:
                self.dut.powergood_i.value = 0
                self.logger.info("Drove powergood_i=0 (glitch)")
            elif item.op is SmcResetOp.POWERGOOD_HI:
                self.dut.powergood_i.value = 1
                self.logger.info("Drove powergood_i=1 (recover)")
            elif item.op is SmcResetOp.COLD_RST_LO:
                self.dut.rst_cold_ni.value = 0
                self.logger.info("Drove rst_cold_ni=0 (assert)")
            elif item.op is SmcResetOp.COLD_RST_HI:
                self.dut.rst_cold_ni.value = 1
                self.logger.info("Drove rst_cold_ni=1 (release)")
            elif item.op is SmcResetOp.COOL_RST_LO:
                self.dut.rst_cool_ni.value = 0
                self.logger.info("Drove rst_cool_ni=0 (assert)")
            elif item.op is SmcResetOp.COOL_RST_HI:
                self.dut.rst_cool_ni.value = 1
                self.logger.info("Drove rst_cool_ni=1 (release)")
            else:
                raise ValueError(f"unsupported SmcResetOp: {item.op}")
            self.ap.write(item)
            self.seq_item_port.item_done()

    def _sample(self, item: SmcResetItem) -> None:
        dut = self.dut
        signals = {
            "powergood_stable": dut.powergood_stable_o,
            "rst_cold_stable_ref_clk_n": dut.rst_cold_stable_ref_clk_no,
            "rst_primary_ref_clk_n": dut.rst_primary_ref_clk_no,
            "rst_primary_smc_clk_n": dut.rst_primary_smc_clk_no,
            "rst_wdt_smc_clk_n": dut.rst_wdt_smc_clk_no,
        }
        all_resolvable = True
        for attr, sig in signals.items():
            v = sig.value
            if v.is_resolvable:
                setattr(item, attr, int(v))
            else:
                all_resolvable = False
                setattr(item, attr, -1)
        item.resolvable = all_resolvable
        self.logger.info("Sampled %s", item)


class SmcResetAgent(uvm_agent):

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcResetDriver("driver", self)

    def connect_phase(self) -> None:
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap
