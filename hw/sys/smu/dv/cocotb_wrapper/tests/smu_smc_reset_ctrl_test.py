# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_reset_ctrl_test - primary/cold/periph reset release under the SMU wrapper."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from seq_lib.smu_tb_pins import cold_stable_reset, smc_primary_reset
from smu_base_test import smu_base_test

HOLD_CYCLES = 100


def _sample1(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_smc_reset_ctrl_test(smu_base_test):
    """Assert cold/primary/periph resets released and stay high after settle."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        sb.expect_eq(
            "rst_cold_stable_ref_clk_no",
            _sample1(cold_stable_reset(dut), "rst_cold_stable_ref_clk_no"),
            1,
            evidence="RST_COLD_STABLE_1",
        )
        sb.expect_eq(
            "rst_ref_domain_released",
            _sample1(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no"),
            1,
            evidence="RST_REF_DOMAIN_1",
        )
        sb.expect_eq(
            "rst_primary_smc_clk_no",
            _sample1(smc_primary_reset(dut), "rst_primary_smc_clk_no"),
            1,
            evidence="RST_PRIMARY_SMC_1",
        )
        sb.expect_eq(
            "rst_periph_domain_released",
            _sample1(dut.rst_primary_periph_clk_no, "rst_primary_periph_clk_no"),
            1,
            evidence="RST_PERIPH_DOMAIN_1",
        )

        for cycle in range(HOLD_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            samples = {
                "rst_cold_stable_ref_clk_no": _sample1(
                    cold_stable_reset(dut), "rst_cold_stable_ref_clk_no"
                ),
                "rst_primary_ref_clk_no": _sample1(
                    dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no"
                ),
                "rst_primary_smc_clk_no": _sample1(
                    smc_primary_reset(dut), "rst_primary_smc_clk_no"
                ),
                "rst_primary_periph_clk_no": _sample1(
                    dut.rst_primary_periph_clk_no, "rst_primary_periph_clk_no"
                ),
            }
            for name, val in samples.items():
                if val != 1:
                    raise AssertionError(f"{name} deasserted mid-hold cycle={cycle} last={val}")

        sb.expect_eq(
            "rst_cold_stable holds high",
            _sample1(cold_stable_reset(dut), "rst_cold_stable_ref_clk_no"),
            1,
            evidence="RST_COLD_HOLD",
        )
        sb.expect_eq(
            "rst_ref_domain holds high",
            _sample1(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no"),
            1,
            evidence="RST_REF_HOLD",
        )
        sb.expect_eq(
            "rst_primary_smc holds high",
            _sample1(smc_primary_reset(dut), "rst_primary_smc_clk_no"),
            1,
            evidence="RST_SMC_HOLD",
        )
        sb.expect_eq(
            "rst_periph_domain holds high",
            _sample1(dut.rst_primary_periph_clk_no, "rst_primary_periph_clk_no"),
            1,
            evidence="RST_PERIPH_HOLD",
        )

        self.logger.info(
            "smu_smc_reset_ctrl_test: cold/primary/periph resets OK (hold=%d)",
            HOLD_CYCLES,
        )
