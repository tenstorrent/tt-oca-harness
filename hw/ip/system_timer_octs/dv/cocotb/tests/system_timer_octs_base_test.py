# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the System Timer OCTS IP-level cocotb tests.

The bench drives ``system_timer_octs_tb_top``, a primary timer wired to a
secondary timer on separate clocks:

* each instance's AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite
  master (``OcahAxiLiteMasterAgent`` on the flattened ``primary_axil_*`` and
  ``secondary_axil_*`` pins, consumed through ``agent.sequence`` only);
* the two ``*_is_primary`` mode inputs;
* the ``sync_load`` and ``cnt_credit`` wires between the instances, both
  64-bit counters, the GPIO enables and the credit debug outputs, all
  observed on pins.

Register addresses, field layouts and reset values come from the generated
RDL header. The synchronization contract (rtl/system_timer_octs_core.sv):
the primary loads its preset on TIMER_START and counts one per clock; it
pulses ``sync_load`` once at start and ``cnt_credit`` every CREDIT_VAL
clocks, each pulse PULSE_WIDTH clocks wide. The secondary loads its preset
on the synchronized ``sync_load`` edge, advances by STEP per clock while it
holds credits, and re-aligns to the expected count on every credit edge.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import cocotb
import system_timer_octs_reg as REG
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer, with_timeout
from cocotb.utils import get_sim_time
from ocah_axi_vip import OcahAxiLiteMasterAgent

DEFAULT_CLK_PERIOD_NS = 10

PRIMARY = "primary"
SECONDARY = "secondary"
PORTS = (PRIMARY, SECONDARY)

# The bench's synchronization parameters (CTRL fields) and presets.
CREDIT_VAL = 10
PULSE_WIDTH = 2
STEP = 1
PRESET_PRIMARY = 0x64
PRESET_SECONDARY = 0x6A

# Cycles for a pulse to cross the secondary's input flop, two-flop
# synchronizer and edge detector, with slack.
SYNC_LATENCY_CYCLES = 8


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def reg_mask(reg_t) -> int:
    """Mask of the architected (non-reserved) bits of a generated register struct."""
    mask = 0
    offset = 0
    for name, _ctype, width in reg_t._fields_:
        if not name.startswith(("rsvd", "reserved")):
            mask |= ((1 << width) - 1) << offset
        offset += width
    return mask


def ctrl_word(
    credit_val: int = CREDIT_VAL, pulse_width: int = PULSE_WIDTH, step: int = STEP
) -> int:
    ctrl = REG.SYSTEM_TIMER_OCTS_CTRL_reg_u()
    ctrl.f.credit_val = credit_val
    ctrl.f.pulse_width = pulse_width
    ctrl.f.step = step
    return ctrl.val


@dataclass
class ClockPair:
    primary_ns: int = DEFAULT_CLK_PERIOD_NS
    secondary_ns: int = DEFAULT_CLK_PERIOD_NS


class SystemTimerOctsTb:
    """Clocks, reset, one AXI master per instance, and pin-level observers."""

    def __init__(self, dut, name: str = "system_timer_octs_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agents = {}
        self.seqs = {}
        self.clock_tasks = []
        self.clocks = ClockPair()

    def clk(self, port: str):
        return self.dut.clk_primary if port == PRIMARY else self.dut.clk_secondary

    def count(self, port: str) -> int:
        return int(getattr(self.dut, f"{port}_count").value)

    async def start(self, clocks: ClockPair | None = None) -> None:
        """Init inputs, start both clocks, bring up both AXI masters, run reset."""
        dut = self.dut
        self.clocks = clocks or ClockPair()
        dut.primary_is_primary.value = 1
        dut.secondary_is_primary.value = 0
        dut.rst_n.value = 0
        self.start_clocks()

        for port in PORTS:
            agent = OcahAxiLiteMasterAgent.from_prefix(
                dut,
                f"{port}_axil",
                self.clk(port),
                dut.rst_n,
                name=f"{port}_axil_host",
                timeout_cycles=1000,
            )
            self.agents[port] = agent
            self.seqs[port] = agent.sequence
            await agent.start()
        await self.reset()
        self.log.info(
            "bring-up complete: primary clock %d ns, secondary clock %d ns",
            self.clocks.primary_ns,
            self.clocks.secondary_ns,
        )

    def start_clocks(self) -> None:
        dut = self.dut
        self.clock_tasks = [
            cocotb.start_soon(Clock(dut.clk_primary, self.clocks.primary_ns, "ns").start()),
            cocotb.start_soon(Clock(dut.clk_secondary, self.clocks.secondary_ns, "ns").start()),
        ]

    async def reclock(self, clocks: ClockPair) -> None:
        """Stop both clocks, restart them at new periods, and reset the timers."""
        for task in self.clock_tasks:
            task.cancel()
        await Timer(max(self.clocks.primary_ns, self.clocks.secondary_ns), "ns")
        self.clocks = clocks
        self.start_clocks()
        await self.reset()
        self.log.info(
            "reclocked: primary %d ns, secondary %d ns", clocks.primary_ns, clocks.secondary_ns
        )

    async def reset(self) -> None:
        dut = self.dut
        dut.rst_n.value = 0
        await ClockCycles(dut.clk_primary, 10)
        await ClockCycles(dut.clk_secondary, 2)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk_primary, 10)
        await ClockCycles(dut.clk_secondary, 10)

    # ------------------------------------------------------------------
    # Register access
    # ------------------------------------------------------------------

    async def write(self, port: str, addr: int, value: int) -> None:
        await self.seqs[port].write(addr, value)

    async def read(self, port: str, addr: int) -> int:
        return await self.seqs[port].read(addr)

    async def read_u(self, port: str, union_t, addr: int):
        reg = union_t()
        reg.val = await self.read(port, addr)
        return reg

    async def configure(
        self,
        port: str,
        *,
        preset: int,
        credit_val: int = CREDIT_VAL,
        pulse_width: int = PULSE_WIDTH,
        step: int = STEP,
    ) -> None:
        await self.write(port, REG.TIMER_PRESET_LO_REG_ADDR, preset & 0xFFFF_FFFF)
        await self.write(port, REG.TIMER_PRESET_HI_REG_ADDR, preset >> 32)
        await self.write(port, REG.CTRL_REG_ADDR, ctrl_word(credit_val, pulse_width, step))
        self.log.info(
            "%s: preset 0x%x, credit %d, pulse width %d, step %d",
            port,
            preset,
            credit_val,
            pulse_width,
            step,
        )

    async def start_primary(self) -> None:
        await self.write(PRIMARY, REG.TIMER_START_REG_ADDR, 1)

    # ------------------------------------------------------------------
    # Pin-level observation
    # ------------------------------------------------------------------

    async def measure_pulse(self, signal, clock, what: str, timeout_cycles: int) -> int:
        """Wait for one pulse on ``signal``; return its width in ``clock`` cycles."""
        period_ns = (
            self.clocks.primary_ns if clock is self.dut.clk_primary else self.clocks.secondary_ns
        )
        await with_timeout(RisingEdge(signal), timeout_cycles * period_ns, "ns")
        rose_ns = get_sim_time("ns")
        width = 0
        while True:
            await FallingEdge(clock)
            if int(signal.value) == 0:
                break
            width += 1
            assert width <= timeout_cycles, f"{what}: pulse never ended"
        self.log.info("%s: rose at %d ns, %d clock(s) wide", what, rose_ns, width)
        return width

    async def credit_period(self, timeout_cycles: int) -> int:
        """Primary cycles between two consecutive cnt_credit rising edges."""
        dut = self.dut
        period_ns = self.clocks.primary_ns
        await with_timeout(RisingEdge(dut.cnt_credit), timeout_cycles * period_ns, "ns")
        cycles = 0
        await FallingEdge(dut.clk_primary)
        while True:
            await FallingEdge(dut.clk_primary)
            cycles += 1
            if int(dut.cnt_credit.value) == 1 and cycles > PULSE_WIDTH:
                return cycles
            assert cycles <= timeout_cycles, "cnt_credit: no second pulse"

    async def sample_counts(
        self, samples: int, min_gap: int, max_gap: int, rng
    ) -> list[tuple[int, int]]:
        """Sample (primary, secondary) counts on primary falling edges at random gaps."""
        pairs = []
        for _ in range(samples):
            await FallingEdge(self.dut.clk_primary)
            pairs.append((self.count(PRIMARY), self.count(SECONDARY)))
            await ClockCycles(self.dut.clk_primary, rng.randint(min_gap, max_gap))
        return pairs


__all__ = [
    "CREDIT_VAL",
    "DEFAULT_CLK_PERIOD_NS",
    "PORTS",
    "PRESET_PRIMARY",
    "PRESET_SECONDARY",
    "PRIMARY",
    "PULSE_WIDTH",
    "REG",
    "SECONDARY",
    "STEP",
    "SYNC_LATENCY_CYCLES",
    "ClockPair",
    "SystemTimerOctsTb",
    "ctrl_word",
    "random_seed",
    "reg_mask",
]
