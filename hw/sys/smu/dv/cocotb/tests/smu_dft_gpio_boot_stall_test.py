# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dft_gpio_boot_stall_test - GPIO pad boot-stall gates fuse_reset.

SMC padring maps lsio_pad2core_data[57] to boot_stall_from_bp. With JTAG
override idle, GPIO stall is sticky across cold reset until cleared.

Stimulus uses TB ``gpio_boot_stall_drive_i`` (OR into pad2core).

Real checkers:
  1. Drive pad bit[57]=1 across cold reset -> fuse_reset_n_delayed_o stays 0
  2. Clear pad -> fuse_reset rises
  3. Re-assert pad after release does not re-gate (sticky)
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_axi_helpers import wait_signal_high
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dft_gpio_boot_stall_test(smu_base_test):
    """GPIO boot-stall sticky gating of fuse_reset_n_delayed_o."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq(
            "fuse_reset high after bring-up",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        stall = dut.gpio_boot_stall_drive_i

        # Assert GPIO stall, then cold-reset so sticky latch samples it.
        stall.value = 1
        await ClockCycles(dut.clk_smu_i, 8)

        self.logger.info("Pulsing rst_cold_ni with GPIO boot-stall asserted")
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            smc_primary_reset(dut),
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary after GPIO stall reset",
        )
        await ClockCycles(dut.clk_smu_i, 64)

        sb.expect_eq(
            "fuse_reset gated by GPIO boot-stall",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
            evidence="STALL_COLD_STICKY",
        )

        stall.value = 0
        await wait_signal_high(
            dut.fuse_reset_n_delayed_o,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="fuse_reset after GPIO clear",
        )
        sb.expect_eq(
            "fuse_reset released after GPIO clear",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        # Sticky: re-assert must not re-gate once released.
        stall.value = 1
        await ClockCycles(dut.clk_smu_i, 64)
        sb.expect_eq(
            "fuse_reset stays high on sticky re-assert",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
            evidence="STALL_REASSERT_STICKY",
        )

        stall.value = 0
        await ClockCycles(dut.clk_smu_i, 16)
        self.logger.info("smu_dft_gpio_boot_stall_test: GPIO stall sticky path OK")
