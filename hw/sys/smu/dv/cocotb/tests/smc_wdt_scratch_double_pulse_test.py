# SPDX-License-Identifier: Apache-2.0
"""smc_wdt_scratch_double_pulse_test - P3-H5c WDT second-timeout double pulse.

Extends P2-I11b with a second Force pulse and mid re-seed:

  1. Seed cold + cold_warm via JTAG2AXI
  2. Pulse1: cold sticky retained; cold_warm cleared
  3. Re-seed cold_warm (new pattern); cold sticky unchanged
  4. Pulse2: cold still sticky; re-seeded cold_warm cleared again

Must FAIL if cold sticky clears on either pulse or cold_warm survives a pulse.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

SCRATCH_COLD = 0xC000_2800
SCRATCH_COLD_WARM = 0xC000_2880
PAT_COLD = 0xC0FF_EE01
PAT_WARM1 = 0xCAFE_B0BA
PAT_WARM2 = 0xDEAD_BEEF


async def _pulse_wdt_second(dut, cycles: int = 64) -> None:
    wdt_second = dut.u_dut.u_smc.wdt_second_timeout_o
    wdt_second.value = Force(1)
    try:
        await ClockCycles(dut.clk_smu_i, cycles)
    finally:
        wdt_second.value = Release()
    await ClockCycles(dut.clk_smu_i, 256)


@pyuvm.test()
class smc_wdt_scratch_double_pulse_test(smu_base_test):
    """Two WDT warm pulses with mid re-seed of cold-warm scratch."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            st, _ = await jtag2axi_single_write(jtag, SCRATCH_COLD, PAT_COLD)
            sb.expect_eq("cold seed write", st, J2A_STATUS_SUCCESS, evidence="WDT_DOUBLE_PULSE")
            st, _ = await jtag2axi_single_write(jtag, SCRATCH_COLD_WARM, PAT_WARM1)
            sb.expect_eq("warm1 seed write", st, J2A_STATUS_SUCCESS)

            await _pulse_wdt_second(dut)
            for _ in range(8):
                await jtag.step_tms(0)

            st_c, cold = await jtag2axi_single_read(jtag, SCRATCH_COLD)
            sb.expect_eq("pulse1 cold read status", st_c, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "pulse1 cold sticky retained",
                int(cold) & 0xFFFF_FFFF,
                PAT_COLD,
            )
            st_w, warm = await jtag2axi_single_read(jtag, SCRATCH_COLD_WARM)
            sb.expect_eq("pulse1 warm read status", st_w, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "pulse1 cold_warm cleared",
                int(warm) & 0xFFFF_FFFF,
                0,
            )

            # Mid re-seed: only cold_warm; cold must stay PAT_COLD.
            st, _ = await jtag2axi_single_write(jtag, SCRATCH_COLD_WARM, PAT_WARM2)
            sb.expect_eq("warm2 re-seed write", st, J2A_STATUS_SUCCESS)
            st_r, rb = await jtag2axi_single_read(jtag, SCRATCH_COLD_WARM)
            sb.expect_eq("warm2 re-seed readback", int(rb) & 0xFFFF_FFFF, PAT_WARM2)
            st_c2, cold2 = await jtag2axi_single_read(jtag, SCRATCH_COLD)
            sb.expect_eq(
                "cold unchanged across re-seed",
                int(cold2) & 0xFFFF_FFFF,
                PAT_COLD,
            )

            await _pulse_wdt_second(dut)
            for _ in range(8):
                await jtag.step_tms(0)

            st_c3, cold3 = await jtag2axi_single_read(jtag, SCRATCH_COLD)
            sb.expect_eq("pulse2 cold read status", st_c3, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "pulse2 cold sticky still retained",
                int(cold3) & 0xFFFF_FFFF,
                PAT_COLD,
            )
            st_w2, warm2 = await jtag2axi_single_read(jtag, SCRATCH_COLD_WARM)
            sb.expect_eq("pulse2 warm read status", st_w2, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "pulse2 cold_warm cleared again",
                int(warm2) & 0xFFFF_FFFF,
                0,
            )
        finally:
            release_forced(forced)

        self.logger.info("smc_wdt_scratch_double_pulse_test: double pulse + re-seed OK")
