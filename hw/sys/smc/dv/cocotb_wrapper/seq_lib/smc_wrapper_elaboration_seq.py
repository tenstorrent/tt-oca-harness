# SPDX-License-Identifier: Apache-2.0
"""Structural OSS smc_wrapper sequence used before firmware bring-up."""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge


class SmcWrapperElaborationSeq:
    """Check pad-level reset / powergood propagation over repeated pulses."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.rng = random.Random(test.random_seed())

    async def wait_value(self, signal, expected: int, name: str, limit: int = 500) -> int:
        for cycle in range(limit):
            await RisingEdge(self.dut.clk_ref_i)
            observed = self.test.read_int(signal, name)
            if observed == expected:
                self.log.info(
                    "%s reached expected=%d at poll cycle %d", name, expected, cycle
                )
                return cycle
        observed = self.test.read_int(signal, name)
        raise AssertionError(
            f"{name} timeout: expected={expected} observed={observed} limit={limit}"
        )

    async def run(self) -> None:
        self.log.info("=" * 70)
        self.log.info("TEST: OSS smc_wrapper pad-level reset / powergood")
        self.log.info("=" * 70)

        assert self.test.read_int(self.dut.dut_present_o, "dut_present_o") == 1

        await self.wait_value(self.dut.powergood_o, 1, "powergood_o")
        await self.wait_value(self.dut.rst_cold_n_o, 1, "rst_cold_n_o")
        await self.wait_value(self.dut.smc_reset_n_o, 1, "smc_reset_n_o")

        for iteration in range(2):
            hold_cycles = self.rng.randint(2, 5)
            self.log.info(
                "Reset iteration %d: assert cold reset for %d ref-clock cycles",
                iteration,
                hold_cycles,
            )
            self.dut.rst_cold_ni.value = 0
            await self.wait_value(self.dut.rst_cold_n_o, 0, "rst_cold_n_o")
            await ClockCycles(self.dut.clk_ref_i, hold_cycles)
            self.dut.rst_cold_ni.value = 1
            await self.wait_value(self.dut.rst_cold_n_o, 1, "rst_cold_n_o")

        self.log.info("PASS: OSS smc_wrapper elaborated; reset remained responsive")
