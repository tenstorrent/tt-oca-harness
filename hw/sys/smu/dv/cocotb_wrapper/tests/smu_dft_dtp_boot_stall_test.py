# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dft_dtp_boot_stall_test - DTP DEBUG_CONTROL boot-stall -> SMC fuse_reset.

Real checkers (must FAIL if wrong):
  1. DEBUG_CONTROL write updates jtag_boot_stall_ovrd / jtag_boot_stall
  2. TDR readback matches written fields
  3. With stall asserted across cold reset (TRST held deasserted),
     smc_fuse_reset_n_delayed_o stays low until stall cleared
  4. Sticky: re-asserting stall after release does not re-gate fuse_reset

The SMC eFuse sense runs for real on the wrapper: checker 3 samples the gate
only after smc_fuse_sense_done_o has risen for the cold reset, and bounds the
release after the clear by the gate path, not the sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_axi_helpers import wait_signal_high
from seq_lib.smu_fuse_gate_helpers import (
    arm_gate_release,
    expect_gate_held_after_sense,
    expect_gate_release,
    expect_no_regate,
    expect_release_after_sense,
)
from seq_lib.smu_jtag_helpers import (
    make_smu_jtag_tap,
    pack_debug_control,
)
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dft_dtp_boot_stall_test(smu_base_test):
    """DTP boot-stall override gates SMC fuse_reset with sticky release."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        log = self.logger

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        # --- Phase A: DEBUG_CONTROL <-> DTP outputs ---
        sb.expect_eq("boot_stall_ovrd idle", int(dut.jtag_boot_stall_ovrd.value), 0)
        sb.expect_eq("boot_stall idle", int(dut.jtag_boot_stall.value), 0)
        # Bring-up: no stall, so the sense completes and the release follows it.
        await expect_release_after_sense(
            dut, sb, log, phase="bring-up", name="fuse_reset released after bring-up sense"
        )

        combinations = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for ovrd, stall in combinations:
            value = pack_debug_control(boot_stall_ovrd=ovrd, boot_stall=stall)
            await jtag.write("DEBUG_CONTROL", value)
            await ClockCycles(dut.clk_smu_i, 8)
            sb.expect_eq(
                f"jtag_boot_stall_ovrd combo ovrd={ovrd} stall={stall}",
                int(dut.jtag_boot_stall_ovrd.value),
                ovrd,
            )
            sb.expect_eq(
                f"jtag_boot_stall combo ovrd={ovrd} stall={stall}",
                int(dut.jtag_boot_stall.value),
                stall,
            )
            readback = await jtag.read("DEBUG_CONTROL", shift_value=value)
            sb.expect_eq(
                f"DEBUG_CONTROL readback ovrd={ovrd} stall={stall}",
                int(readback) & 0xF,
                value & 0xF,
            )

        # --- Phase B: SMC fuse_reset gating across cold reset ---
        await jtag.write(
            "DEBUG_CONTROL",
            pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall asserted ovrd", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("stall asserted val", int(dut.jtag_boot_stall.value), 1)

        # Cold reset pulse; keep powergood and TRST high so DEBUG_CONTROL persists.
        log.info("Pulsing rst_cold_ni with boot-stall held (TRST stays high)")
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
            name="rst_primary_smc_clk_no after stall reset",
        )
        await ClockCycles(dut.clk_smu_i, 64)

        sb.expect_eq(
            "jtag_boot_stall_ovrd survives cold reset",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "jtag_boot_stall survives cold reset",
            int(dut.jtag_boot_stall.value),
            1,
        )
        # The cold reset restarted the sense; the gate is judged only once it is done.
        await gate_held

        # Release stall -> fuse_reset must rise within the gate path.
        armed_ns = arm_gate_release(dut, sb, name="fuse_reset released after stall clear")
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall cleared ovrd", int(dut.jtag_boot_stall_ovrd.value), 0)
        sb.expect_eq("stall cleared val", int(dut.jtag_boot_stall.value), 0)
        await expect_gate_release(
            dut,
            sb,
            log,
            armed_ns=armed_ns,
            phase="stall clear",
            name="fuse_reset released after stall clear",
        )

        # Sticky: re-assert stall must NOT re-gate fuse_reset until next primary reset.
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
        log.info("smu_dft_dtp_boot_stall_test: DTP+SMC boot-stall checks done")
