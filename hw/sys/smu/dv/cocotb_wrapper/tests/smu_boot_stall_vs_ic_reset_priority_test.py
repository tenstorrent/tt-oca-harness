# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_boot_stall_vs_ic_reset_priority_test - stall vs IC_RESET priority.

Boot-stall (DEBUG_CONTROL) and IC_RESET are independent TDRs. After stall is
made sticky across cold (fuse gated), this corner checks:

  1. IC_RESET warm then cold while stall sticky: ovrd asserts; stall survives;
     the cold override asserts the SMC primary reset
  2. IC_RESET DEFAULT: domain ovrd clears; the primary reset releases again and
     the still-sticky stall gates fuse_reset across that reset too
  3. TRST clears stall AND IC_RESET; fuse_reset releases

The SMC eFuse sense runs for real on the wrapper: every gated fuse_reset is
sampled only after smc_fuse_sense_done_o has risen for the primary reset it
follows (the cold reset, then the IC_RESET-driven one), and the release after
TRST is bounded by the gate path, not the sense.

Must FAIL if IC_RESET clears stall, stall survives TRST, or wrong IC_RESET
domain asserts while stall is active.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_axi_helpers import wait_signal_high
from seq_lib.smu_fuse_gate_helpers import (
    FUSE_GATE_RELEASE_BOUND_CYCLES,
    arm_gate_release,
    expect_gate_held_after_sense,
    expect_gate_release,
    expect_release_after_sense,
    wait_level,
)
from seq_lib.smu_jtag_helpers import (
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_SMC_COLD_PORT,
    SMU_IC_RESET_SMC_WARM_PORT,
    make_smu_jtag_tap,
    pack_debug_control,
    pack_ic_reset_ports,
    read_smc_reset_ctrl_bit,
)
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_boot_stall_vs_ic_reset_priority_test(smu_base_test):
    """Stall sticky isolation vs IC_RESET; TRST clears both."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        log = self.logger

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        # Bring-up: no stall, so the sense completes and the release follows it.
        await expect_release_after_sense(
            dut, sb, log, phase="bring-up", name="fuse_reset released after bring-up sense"
        )

        # --- Make stall sticky across cold (the same window as
        #     smu_boot_stall_jtag_cold_reset_matrix_test uses) ---
        await jtag.write(
            "DEBUG_CONTROL",
            pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall ovrd before cold", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("stall val before cold", int(dut.jtag_boot_stall.value), 1)

        log.info("Cold reset with TRST held high (stall sticky + fuse gate)")
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        # Arm the sense-done observation at the release itself: the flag reads 0
        # in reset, and the settle below can outlast the whole sense.
        gate_held = cocotb.start_soon(
            expect_gate_held_after_sense(
                dut,
                sb,
                log,
                phase="cold+stall",
                name="fuse_reset gated while stall sticky",
            )
        )
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
        # The cold reset restarted the sense; the gate is judged only once it is done.
        await gate_held

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
            int(dut.smc_fuse_reset_n_delayed_o.value),
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
        # The cold override drives the SMC primary reset; under it fuse_reset is
        # in reset, so the gate is judged again once that reset releases below.
        await wait_level(
            smc_primary_reset(dut),
            dut.clk_smu_i,
            expect=0,
            timeout_cycles=FUSE_GATE_RELEASE_BOUND_CYCLES,
            name="rst_primary under IC_RESET cold ovrd",
        )
        sb.expect_eq(
            "primary reset asserted by IC_RESET cold ovrd",
            int(smc_primary_reset(dut).value),
            0,
        )
        sb.expect_eq(
            "fuse_reset low under IC_RESET cold ovrd",
            int(dut.smc_fuse_reset_n_delayed_o.value),
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
        await wait_signal_high(
            smc_primary_reset(dut),
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary after IC_RESET DEFAULT",
        )
        await ClockCycles(dut.clk_smu_i, 64)
        sb.expect_eq(
            "stall sticky after IC_RESET DEFAULT",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        # That primary reset restarted the sense and re-latched the sticky stall.
        await expect_gate_held_after_sense(
            dut,
            sb,
            log,
            phase="IC_RESET DEFAULT",
            name="fuse still gated after IC_RESET DEFAULT",
        )

        # --- TRST clears stall and IC_RESET ---
        armed_ns = arm_gate_release(dut, sb, name="fuse_reset high after TRST")
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
        await expect_gate_release(
            dut,
            sb,
            log,
            armed_ns=armed_ns,
            phase="TRST clear",
            name="fuse_reset high after TRST",
        )

        log.info("smu_boot_stall_vs_ic_reset_priority_test: stall|IC_RESET isolation+TRST OK")
