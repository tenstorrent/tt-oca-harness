# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_cold_reset_async_assert_test - asynchronous cold-reset assertion.

Closes SMU-RST-COLD.S1 against the rst_cold_ni row of port_table.adoc, on the
`--dut smu` production wrapper built with compile_smu_chiplet: every
wrapper clock is stopped and held static, rst_cold_ni is asserted, and
rst_cold_stable_ref_clk_no, rst_primary_ref_clk_no, rst_primary_smc_clk_no,
rst_primary_periph_clk_no and the SMC and DTP primary-reset inputs are read
asserted before any clock edge occurs; the clocks are then restarted and the
release observed so the DUT ends the run out of reset.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_cold_reset_async_assert_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.clock import Clock
from seq_lib.smu_cold_reset_async_assert_seq import smu_cold_reset_async_assert_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_cold_reset_async_assert_test(smu_base_test):
    """rst_cold_ni asserts the reset outputs with all clocks stopped."""

    use_shared_env = True

    def start_clocks(self) -> None:
        dut = cocotb.top
        self.clocks = [
            Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, unit="ns"),
            Clock(dut.clk_smu_i, self.cfg.smu_clk_period_ns, unit="ns"),
            Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, unit="ns"),
            Clock(dut.clk_sep_wdt_i, self.cfg.sep_wdt_clk_period_ns, unit="ns"),
        ]
        for clock in self.clocks:
            clock.start()

    async def run_scenario(self) -> None:
        await smu_cold_reset_async_assert_seq(self).run()
