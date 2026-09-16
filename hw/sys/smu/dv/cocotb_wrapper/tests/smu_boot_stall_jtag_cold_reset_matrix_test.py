# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_boot_stall_jtag_cold_reset_matrix_test - boot-stall sticky matrix.

Deepens smu_dft_dtp_boot_stall_test with an explicit TRST-clear contrast:

  1. Stall asserted across cold reset (TRST held high) stays sticky; fuse gated
  2. TRST pulse (reset_tap) clears DEBUG_CONTROL / boot-stall exports
  3. fuse_reset releases after TRST clear
  4. Sticky: re-assert stall without primary reset does not re-gate fuse_reset
  5. Source priority with the GPIO pad driving as well: the SMC combines the
     two sources as ovrd ? jtag_val : pad, so an override reading 0 releases
     the gate while the pad is still driving 1

The SMC eFuse sense runs for real on the wrapper: every fuse_reset compare is
anchored on smc_fuse_sense_done_o for the primary reset it follows, and the
release after the clear is bounded by the gate path, not the sense.

Must FAIL if sticky broken, if TRST fails to clear DEBUG_CONTROL, or if the
GPIO pad holds the gate shut against an override that reads 0.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_axi_helpers import wait_signal_high
from seq_lib.smu_fuse_gate_helpers import (
    FUSE_GATE_HOLD_CYCLES,
    arm_gate_release,
    expect_gate_held_after_sense,
    expect_gate_release,
    expect_no_regate,
    expect_release_after_sense,
    hold_level,
)
from seq_lib.smu_jtag_helpers import make_smu_jtag_tap, pack_debug_control
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_boot_stall_jtag_cold_reset_matrix_test(smu_base_test):
    """Boot-stall cold-reset sticky + TRST clear matrix."""

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

        # --- Assert stall; cold reset with TRST high (DEBUG sticky) ---
        await jtag.write(
            "DEBUG_CONTROL",
            pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall ovrd before cold", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("stall val before cold", int(dut.jtag_boot_stall.value), 1)

        log.info("Cold reset with TRST held high (stall sticky)")
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
                evidence="STALL_COLD_STICKY",
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
            "stall ovrd survives cold (TRST high)",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "stall val survives cold (TRST high)",
            int(dut.jtag_boot_stall.value),
            1,
        )
        # The cold reset restarted the sense; the gate is judged only once it is done.
        await gate_held

        # --- TRST pulse clears DEBUG_CONTROL ---
        armed_ns = arm_gate_release(dut, sb, name="fuse_reset high after TRST clear")
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
        await expect_gate_release(
            dut,
            sb,
            log,
            armed_ns=armed_ns,
            phase="TRST clear",
            name="fuse_reset high after TRST clear",
            evidence="STALL_TRST_CLEAR",
        )

        # --- Sticky re-assert: must NOT re-gate fuse_reset ---
        await jtag.write(
            "DEBUG_CONTROL",
            pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("re-assert ovrd", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("re-assert val", int(dut.jtag_boot_stall.value), 1)
        await expect_no_regate(
            dut,
            sb,
            log,
            phase="sticky re-assert",
            name="fuse_reset stays high on sticky re-assert",
            evidence="STALL_REASSERT_STICKY",
        )

        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)

        # --- GPIO pad alone gates, then both sources, then override-low wins ---
        # The pad-only leg is the positive control for the two that follow: it
        # proves the pad really reaches boot_stall_from_bp on this run, so a
        # later release cannot be credited to a pad that was never driving.
        dut.gpio_boot_stall_drive_i.value = 1
        await ClockCycles(dut.clk_smu_i, 8)

        log.info("Cold reset with the GPIO pad driving and the JTAG override idle")
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            smc_primary_reset(dut),
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary after cold+GPIO stall",
        )
        await ClockCycles(dut.clk_smu_i, 64)
        sb.expect_eq("pad-only leg: jtag ovrd idle", int(dut.jtag_boot_stall_ovrd.value), 0)
        await expect_gate_held_after_sense(
            dut,
            sb,
            log,
            phase="cold+GPIO pad only",
            name="fuse_reset gated by the GPIO pad with the override idle",
            evidence="STALL_PAD_ONLY",
        )

        # Both sources asserted: the override selects its own 1, which agrees
        # with the pad, so the gate stays shut.
        await jtag.write(
            "DEBUG_CONTROL",
            pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_ref_i, 16)
        sb.expect_eq("both sources: jtag ovrd", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("both sources: jtag val", int(dut.jtag_boot_stall.value), 1)
        await hold_level(
            dut.smc_fuse_reset_n_delayed_o,
            dut.clk_smu_i,
            expect=0,
            cycles=FUSE_GATE_HOLD_CYCLES,
            name="smc_fuse_reset_n_delayed_o (both sources)",
        )
        sb.expect_eq(
            "fuse_reset gated with both stall sources asserted",
            int(dut.smc_fuse_reset_n_delayed_o.value),
            0,
            evidence="STALL_BOTH_SOURCES",
        )

        # Override forced low while the pad still drives 1: the mux takes the
        # JTAG value, so the gate must open.
        armed_ns = arm_gate_release(dut, sb, name="fuse_reset released by override-low over pad")
        await jtag.write(
            "DEBUG_CONTROL",
            pack_debug_control(boot_stall_ovrd=1, boot_stall=0),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("override low: ovrd still set", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("override low: val reads 0", int(dut.jtag_boot_stall.value), 0)
        await expect_gate_release(
            dut,
            sb,
            log,
            armed_ns=armed_ns,
            phase="override low over pad",
            name="fuse_reset released by override-low over pad",
            evidence="STALL_OVRD_MASKS_PAD",
        )

        dut.gpio_boot_stall_drive_i.value = 0
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        log.info("smu_boot_stall_jtag_cold_reset_matrix_test: sticky+TRST+source-priority OK")
