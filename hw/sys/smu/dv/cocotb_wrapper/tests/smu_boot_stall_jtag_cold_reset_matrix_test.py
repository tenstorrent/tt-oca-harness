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

Each release (bring-up, TRST clear, override low over the pad) is also followed to the
SMC's first ROM read request: a passive per-clk_smu sampler requires a first read request
at word address 0x0000 (byte 0xC0040000, the cold-reset vector at the base of the ROM)
within a declared liveness bound. The ROM reads seen while the fuse reset is held are
logged as an observation and not graded: the window counted here is not held by the fuse
reset alone, and its fuse-only part is shorter than the first-fetch latency.

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
    RomFetchSampler,
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

# The cold-reset vector is the first word of the ROM (hw/sys/smc/doc/cpu.adoc:145,
# hw/sys/smc/doc/rom.adoc:9-10).
FIRST_WORD_ADDR = 0x0000

EXPECTED_FENCE = [
    "S2 bring-up release",
    "CHK-FIRST-FETCH-AFTER-RELEASE bring-up",
    "S3 cold+stall hold",
    "S4 TRST-clear release",
    "CHK-FIRST-FETCH-AFTER-RELEASE trst-clear",
    "S5 sticky re-assert",
    "S6 pad-only hold",
    "S6 both-sources hold",
    "S7 override-low release",
    "CHK-FIRST-FETCH-AFTER-RELEASE ovrd-low-over-pad",
]


@pyuvm.test()
class smu_boot_stall_jtag_cold_reset_matrix_test(smu_base_test):
    """Boot-stall cold-reset sticky + TRST clear matrix."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        log = self.logger

        sampler = RomFetchSampler(dut, log)
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        sampler.begin_leg("bring-up", record_count_at_arm=True)
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        # Bring-up: no stall, so the sense completes and the release follows it.
        await expect_release_after_sense(
            dut, sb, log, phase="bring-up", name="fuse_reset released after bring-up sense"
        )
        sampler.mark("S2 bring-up release")
        sampler.check_held(log, "bring-up")
        await sampler.check_first_fetch(sb, log, "bring-up", expect_word_addr=FIRST_WORD_ADDR)

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
        sampler.begin_leg("trst-clear")
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
        sampler.mark("S3 cold+stall hold")

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
        sampler.check_clear_to_release(log, "trst-clear")
        sampler.mark("S4 TRST-clear release")
        sampler.check_held(log, "trst-clear")
        await sampler.check_first_fetch(sb, log, "trst-clear", expect_word_addr=FIRST_WORD_ADDR)

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
        sampler.mark("S5 sticky re-assert")

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
        sampler.begin_leg("ovrd-low-over-pad")
        # Armed at the release, as the cold+stall leg is: with the pad the only
        # stall source the sense completes within a hundred clk_smu of the
        # release, inside the settle below.
        pad_gate_held = cocotb.start_soon(
            expect_gate_held_after_sense(
                dut,
                sb,
                log,
                phase="cold+GPIO pad only",
                name="fuse_reset gated by the GPIO pad with the override idle",
                evidence="STALL_PAD_ONLY",
            )
        )
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            smc_primary_reset(dut),
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary after cold+GPIO stall",
        )
        await ClockCycles(dut.clk_smu_i, 64)
        sb.expect_eq("pad-only leg: jtag ovrd idle", int(dut.jtag_boot_stall_ovrd.value), 0)
        await pad_gate_held
        sampler.mark("S6 pad-only hold")

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
        sampler.mark("S6 both-sources hold")

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
        sampler.check_clear_to_release(log, "ovrd-low-over-pad")
        sampler.mark("S7 override-low release")
        sampler.check_held(log, "ovrd-low-over-pad")
        await sampler.check_first_fetch(
            sb, log, "ovrd-low-over-pad", expect_word_addr=FIRST_WORD_ADDR
        )
        sampler.check_fence(sb, log, EXPECTED_FENCE)

        dut.gpio_boot_stall_drive_i.value = 0
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        log.info("smu_boot_stall_jtag_cold_reset_matrix_test: sticky+TRST+source-priority OK")
