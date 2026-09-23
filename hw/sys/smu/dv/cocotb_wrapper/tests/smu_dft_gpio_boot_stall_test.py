# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dft_gpio_boot_stall_test - GPIO pad boot-stall gates fuse_reset.

SMC padring maps lsio_pad2core_data[57] to boot_stall_from_bp. With JTAG
override idle, GPIO stall is sticky across cold reset until cleared.

Stimulus uses TB ``gpio_boot_stall_drive_i`` (OR into pad2core).

Real checkers:
  1. Drive pad bit[57]=1 across cold reset -> smc_fuse_reset_n_delayed_o stays 0
  2. Clear pad -> fuse_reset rises
  3. Re-assert pad after release does not re-gate (sticky)

The SMC eFuse sense runs for real on the wrapper: checker 1 samples the gate
only after smc_fuse_sense_done_o has risen for the cold reset, and checker 2
bounds the release by the gate path, not the sense.
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
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dft_gpio_boot_stall_test(smu_base_test):
    """GPIO boot-stall sticky gating of smc_fuse_reset_n_delayed_o."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        log = self.logger

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)
        # Bring-up: no stall, so the sense completes and the release follows it.
        await expect_release_after_sense(
            dut, sb, log, phase="bring-up", name="fuse_reset released after bring-up sense"
        )

        stall = dut.gpio_boot_stall_drive_i

        # Assert GPIO stall, then cold-reset so sticky latch samples it.
        stall.value = 1
        await ClockCycles(dut.clk_smu_i, 8)

        log.info("Pulsing rst_cold_ni with GPIO boot-stall asserted")
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
                phase="cold+GPIO stall",
                name="fuse_reset gated by GPIO boot-stall",
                evidence="STALL_COLD_STICKY",
            )
        )
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            smc_primary_reset(dut),
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary after GPIO stall reset",
        )
        await ClockCycles(dut.clk_smu_i, 64)

        # The cold reset restarted the sense; the gate is judged only once it is done.
        await gate_held

        armed_ns = arm_gate_release(dut, sb, name="fuse_reset released after GPIO clear")
        stall.value = 0
        await expect_gate_release(
            dut,
            sb,
            log,
            armed_ns=armed_ns,
            phase="GPIO clear",
            name="fuse_reset released after GPIO clear",
        )

        # Sticky: re-assert must not re-gate once released.
        stall.value = 1
        await expect_no_regate(
            dut,
            sb,
            log,
            phase="sticky re-assert",
            name="fuse_reset stays high on sticky re-assert",
            evidence="STALL_REASSERT_STICKY",
        )

        stall.value = 0
        await ClockCycles(dut.clk_smu_i, 16)
        log.info("smu_dft_gpio_boot_stall_test: GPIO stall sticky path OK")
