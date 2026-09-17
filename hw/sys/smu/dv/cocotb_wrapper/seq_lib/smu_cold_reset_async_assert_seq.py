# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_cold_reset_async_assert_test (SMU_107).

With every wrapper clock stopped and held static, rst_cold_ni is asserted and
the cold-stable and primary-reset outputs are required to fall before any
clock edge occurs. The clocks are then restarted and the reset released so the
run ends with the DUT back out of reset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer

from seq_lib.smu_compose_helpers import sample

CLOCK_PINS = ("clk_ref_i", "clk_smu_i", "clk_periph_i", "clk_sep_wdt_i", "jtag_tck")
RESET_OUTPUTS = (
    "rst_cold_n_o",
    "rst_primary_ref_clk_no",
    "rst_primary_smc_clk_n_o",
    "rst_primary_periph_clk_no",
    "obs_smc_rst_n_o",
    "obs_dtp_rst_n_o",
)
QUIET_STEPS = 40
QUIET_STEP_NS = 10
ASSERT_SETTLE_NS = 2
BOUND_REF_CYCLES = 2000


class smu_cold_reset_async_assert_seq:
    """Cold reset asserts through to the reset outputs with no clock running."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.cfg = test.cfg

    def _clock_levels(self) -> dict[str, int]:
        return {name: sample(getattr(self.dut, name), name) for name in CLOCK_PINS}

    def _reset_levels(self) -> dict[str, int]:
        return {name: sample(getattr(self.dut, name), name) for name in RESET_OUTPUTS}

    async def _quiet_window(self, reference: dict[str, int]) -> int:
        changes = 0
        for _ in range(QUIET_STEPS):
            await Timer(QUIET_STEP_NS, unit="ns")
            now = self._clock_levels()
            changes += sum(1 for name in CLOCK_PINS if now[name] != reference[name])
        return changes

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq(
            "all reset outputs released before the clocks stop",
            self._reset_levels(),
            {name: 1 for name in RESET_OUTPUTS},
        )
        clocks = self.test.clocks
        sb.expect_true("clock drivers are owned by the test", len(clocks) >= 4)
        for clock in clocks:
            clock.stop()
        levels = self._clock_levels()
        for name in CLOCK_PINS:
            getattr(dut, name).value = levels[name]
        quiet = await self._quiet_window(levels)
        sb.expect_eq(
            f"no clock edge over {QUIET_STEPS * QUIET_STEP_NS} ns with the clocks stopped",
            quiet,
            0,
        )
        sb.expect_eq(
            "reset outputs still released with the clocks stopped",
            self._reset_levels(),
            {name: 1 for name in RESET_OUTPUTS},
        )
        self.log.info("clocks held at %s; asserting rst_cold_ni", levels)

        dut.rst_cold_ni.value = 0
        await Timer(ASSERT_SETTLE_NS, unit="ns")
        asserted = self._reset_levels()
        still_static = self._clock_levels()
        self.log.info(
            "reset outputs %d ns after the asynchronous assertion: %s", ASSERT_SETTLE_NS, asserted
        )
        sb.expect_eq(
            "clock pins unchanged across the assertion",
            still_static,
            levels,
            evidence="CHK-SMU-RST-COLD-S1",
        )
        sb.expect_eq(
            "cold and primary reset outputs asserted without a clock edge",
            asserted,
            {name: 0 for name in RESET_OUTPUTS},
            evidence="CHK-SMU-RST-COLD-S1",
        )
        quiet = await self._quiet_window(levels)
        sb.expect_eq("clocks still stopped after the assertion", quiet, 0)
        sb.expect_eq(
            "reset outputs stay asserted while the clocks stay stopped",
            self._reset_levels(),
            {name: 0 for name in RESET_OUTPUTS},
            evidence="CHK-SMU-RST-COLD-S1",
        )

        self.test.start_clocks()
        await ClockCycles(dut.clk_ref_i, 4)
        dut.rst_cold_ni.value = 1
        for name in RESET_OUTPUTS:
            sig = getattr(dut, name)
            for cycle in range(BOUND_REF_CYCLES):
                await RisingEdge(dut.clk_ref_i)
                if sample(sig, name) == 1:
                    self.log.info("%s released %d clk_ref after the clocks restarted", name, cycle)
                    break
            else:
                raise AssertionError(
                    f"TIMEOUT {name} still asserted {BOUND_REF_CYCLES} clk_ref after release"
                )
        sb.expect_eq(
            "reset outputs released again once the clocks run",
            self._reset_levels(),
            {name: 1 for name in RESET_OUTPUTS},
        )
