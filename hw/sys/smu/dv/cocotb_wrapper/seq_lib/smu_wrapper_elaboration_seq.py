# SPDX-License-Identifier: Apache-2.0
"""Structural production-wrapper sequence used before firmware bring-up."""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge


class SmuWrapperElaborationSeq:
    """Check profile selection and reset propagation over repeated reset pulses."""

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
        self.log.info("TEST: production smu_wrapper profile and reset propagation")
        self.log.info("=" * 70)

        expected_sep_arg = cocotb.plusargs.get("expected_sep")
        assert expected_sep_arg is not None, "missing required +expected_sep profile contract"
        expected_sep = int(expected_sep_arg, 0)
        expected_reset_during_cold = 0 if expected_sep else 1
        observed_reset_during_cold = self.test.pre_release_sep_reset
        observed_fuse_during_cold = self.test.pre_release_sep_fuse
        assert observed_reset_during_cold == expected_reset_during_cold, (
            "SEP profile mismatch at the real DUT reset output: "
            f"expected reset_n={expected_reset_during_cold} for SEP={expected_sep}, "
            f"observed={observed_reset_during_cold}"
        )
        assert observed_fuse_during_cold == 0, (
            "SEP fuse-done must be inactive during cold reset: "
            f"expected=0 observed={observed_fuse_during_cold}"
        )
        self.log.info(
            "Profile evidence: expected_sep=%d cold_reset_sep_reset_n=%d fuse_done=%d",
            expected_sep,
            observed_reset_during_cold,
            observed_fuse_during_cold,
        )

        await self.wait_value(self.dut.powergood_o, 1, "powergood_o")
        await self.wait_value(self.dut.rst_cold_n_o, 1, "rst_cold_n_o")

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

        self.log.info(
            "PASS: production wrapper elaborated with SEP=%d and reset remained responsive",
            expected_sep,
        )
