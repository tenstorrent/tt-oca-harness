# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Helpers for the Entropy Source native cocotb bench."""

from __future__ import annotations

import logging
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from ocah_axi_vip import OcahAxiLiteMasterAgent

CLK_PERIOD_NS = 10
ROSC_SAMPLE_PERIOD_NS = 34


def random_seed() -> int:
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


class EntropySourceTb:
    """Clock/reset, AXI4-Lite, and deterministic leaf-harness helpers."""

    def __init__(self, dut, name: str = "entropy_source_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None

    def _initialize_inputs(self) -> None:
        dut = self.dut
        dut.rst_n.value = 0
        dut.rosc_sample_clk.value = 0

        dut.fifo_push.value = 0
        dut.fifo_pop.value = 0
        dut.fifo_clear.value = 0
        dut.fifo_wdata.value = 0
        dut.fifo_churn_enable.value = 0

        dut.health_entropy.value = 0
        dut.health_valid.value = 0
        dut.health_enable.value = 0
        dut.health_repetition_limit.value = 0xFF
        dut.health_apt_hi_limit.value = 0xFFFF
        dut.health_apt_lo_limit.value = 0
        dut.health_markov_01_limit.value = 0xFFFF
        dut.health_markov_10_limit.value = 0
        dut.health_window_wrap.value = 0

        dut.decor_enable.value = 0
        dut.decor_noise.value = 0
        dut.decor_bypass.value = 0
        dut.decor_byte_mask.value = 0xFF
        dut.decor_sample_clk_div.value = 0

        dut.sha_entropy_valid.value = 0
        dut.sha_entropy_data.value = 0
        dut.sha_whitened_ready.value = 0
        dut.sha_enable.value = 0

        dut.sampler_select.value = 0
        dut.sampler_enable.value = 0
        dut.sampler_detune.value = 0
        dut.sampler_divide_0.value = 0
        dut.sampler_divide_1.value = 0
        dut.noise_source_enable.value = 0
        dut.noise_source_detune.value = 0

        dut.debug_signals.value = 0
        dut.debug_select_signal.value = 0
        dut.debug_select_div.value = 0
        dut.tune_health_error.value = 0

    async def start(self, *, disable_dut: bool = True) -> None:
        self._initialize_inputs()
        cocotb.start_soon(Clock(self.dut.clk, CLK_PERIOD_NS, unit="ns").start())
        cocotb.start_soon(
            Clock(
                self.dut.rosc_sample_clk,
                ROSC_SAMPLE_PERIOD_NS,
                unit="ns",
            ).start()
        )
        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            self.dut,
            "axil",
            self.dut.clk,
            self.dut.rst_n,
            name="entropy_source_axil_host",
            timeout_cycles=1000,
        )
        self.seq = self.agent.sequence
        await self.agent.start()
        await ClockCycles(self.dut.clk, 5)
        self.dut.rst_n.value = 1
        await ClockCycles(self.dut.clk, 5)
        if disable_dut:
            await self.seq.write(0x4, 0x10000000)

    async def pulse(self, signal, cycles: int = 1) -> None:
        signal.value = 1
        await ClockCycles(self.dut.clk, cycles)
        await FallingEdge(self.dut.clk)
        signal.value = 0

    async def fifo_push_word(self, value: int) -> None:
        await RisingEdge(self.dut.clk)
        self.dut.fifo_wdata.value = value
        self.dut.fifo_push.value = 1
        await RisingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        self.dut.fifo_push.value = 0

    async def fifo_pop_word(self) -> int:
        value = int(self.dut.fifo_rdata.value)
        await self.pulse(self.dut.fifo_pop)
        return value

    async def health_word(self, value: int) -> None:
        await RisingEdge(self.dut.clk)
        self.dut.health_entropy.value = value
        self.dut.health_valid.value = 1
        await RisingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        self.dut.health_valid.value = 0


__all__ = ["CLK_PERIOD_NS", "EntropySourceTb", "random_seed"]
