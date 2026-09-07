# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_boot_stall_vs_ic_reset_priority_test - P3-H5b stall vs IC_RESET priority.

Boot-stall (DEBUG_CONTROL) and IC_RESET are independent TDRs. After stall is
made sticky across cold (fuse gated), this corner checks:

  1. IC_RESET warm then cold while stall sticky: ovrd asserts; stall survives
  2. IC_RESET DEFAULT: domain ovrd clears; stall still sticky; fuse still gated
  3. TRST clears stall AND IC_RESET; fuse_reset releases

Must FAIL if IC_RESET clears stall, stall survives TRST, or wrong IC_RESET
domain asserts while stall is active.
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_axi_helpers import wait_signal_high
from seq_lib.smu_jtag_helpers import (
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_SMC_COLD_PORT,
    SMU_IC_RESET_SMC_WARM_PORT,
    make_smu_jtag_tap,
    pack_debug_control,
    pack_ic_reset_ports,
    read_smc_reset_ctrl_bit,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_boot_stall_vs_ic_reset_priority_test(smu_base_test):
    """Stall sticky isolation vs IC_RESET; TRST clears both."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq(
            "fuse_reset after bring-up",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        # --- Make stall sticky across cold (same window as P2-I3a) ---
        await jtag.write(
            "DEBUG_CONTROL",
            pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall ovrd before cold", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("stall val before cold", int(dut.jtag_boot_stall.value), 1)

        self.logger.info("Cold reset with TRST held high (stall sticky + fuse gate)")
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            smc_primary_reset(dut),
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary after cold+stall",
        )
        await ClockCycles(dut.clk_smu_i, 64)

        sb.expect_eq(
            "stall ovrd sticky after cold",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "stall val sticky after cold",
            int(dut.jtag_boot_stall.value),
            1,
        )
        sb.expect_eq(
            "fuse_reset gated while stall sticky",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- IC_RESET warm while stall sticky ---
        warm_pat = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_SMC_WARM_PORT: 0},
            port_control={SMU_IC_RESET_SMC_WARM_PORT: 0},
        )
        await jtag.write("IC_RESET", warm_pat)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "warm ovrd while stall",
            read_smc_reset_ctrl_bit(dut, "warm_reset_n_ovrd"),
            1,
        )
        sb.expect_eq(
            "cold idle while warm+stall",
            read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "stall survives IC_RESET warm",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
            evidence="STALL_VS_IC_RESET",
        )
        sb.expect_eq(
            "fuse still gated during warm ovrd",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- Switch to cold ovrd while stall sticky ---
        cold_pat = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_SMC_COLD_PORT: 0},
            port_control={SMU_IC_RESET_SMC_COLD_PORT: 0},
        )
        await jtag.write("IC_RESET", cold_pat)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "cold ovrd while stall",
            read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            1,
        )
        sb.expect_eq(
            "warm cleared when cold packed alone",
            read_smc_reset_ctrl_bit(dut, "warm_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "stall survives IC_RESET cold",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "fuse still gated during cold ovrd",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- Release IC_RESET; stall + fuse gate remain ---
        await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "cold cleared by DEFAULT",
            read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "stall sticky after IC_RESET DEFAULT",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "fuse still gated after IC_RESET DEFAULT",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- TRST clears stall and IC_RESET ---
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "stall ovrd cleared by TRST",
            int(dut.jtag_boot_stall_ovrd.value),
            0,
        )
        sb.expect_eq(
            "stall val cleared by TRST",
            int(dut.jtag_boot_stall.value),
            0,
        )
        sb.expect_eq(
            "warm idle after TRST",
            read_smc_reset_ctrl_bit(dut, "warm_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "cold idle after TRST",
            read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            0,
        )
        await wait_signal_high(
            dut.fuse_reset_n_delayed_o,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="fuse_reset after TRST",
        )
        sb.expect_eq(
            "fuse_reset high after TRST",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        self.logger.info(
            "smu_boot_stall_vs_ic_reset_priority_test: stall|IC_RESET isolation+TRST OK"
        )
