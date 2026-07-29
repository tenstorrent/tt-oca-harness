# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_jtag2axi_abort_mid_op_test - P3-H1a abort while SINGLE_OP outstanding.

Uses OTP ungated probe (stays BUSY without bank) so abort is mid-transaction:

  1. Start OTP SINGLE_OP; confirm BUSY
  2. IR change to IDCODE while BUSY
  3. TRST / reset_tap abort
  4. Re-enable fabric JTAG2AXI; VERSION_LO SUCCESS + exact data
  5. Sticky fabric path not corrupted (second VERSION_LO OK)

Must FAIL if post-abort VERSION_LO wrong or sticky CSR corrupted.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_OP_READ,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_OTP_AXSIZE_4B,
    SMC_OTP_DEFAULT_PROBE_ADDR,
    force_jtag2axi_lifecycle_enable,
    force_otp_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    pack_otp_single_op,
    release_forced,
    unpack_otp_single_op,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0


@pyuvm.test()
class smu_dtp_jtag2axi_abort_mid_op_test(smu_base_test):
    """IR change + TRST abort mid-BUSY; fabric VERSION_LO recovers."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        forced_otp = force_otp_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            raw = pack_otp_single_op(
                J2A_OP_READ,
                SMC_OTP_DEFAULT_PROBE_ADDR,
                0,
                wstrb=0,
                size=SMC_OTP_AXSIZE_4B,
            )
            await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
            await ClockCycles(dut.clk_smu_i, 32)

            busy_seen = False
            for _ in range(8):
                capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
                st, _ = unpack_otp_single_op(capt)
                if st == J2A_STATUS_BUSY:
                    busy_seen = True
                    break
                await ClockCycles(dut.clk_smu_i, 8)
            sb.expect_true("OTP mid-op BUSY before abort", busy_seen, evidence="J2A_ABORT_RECOVER")

            # Mid-BUSY IR change to IDCODE (abort scan path).
            idc = await jtag.read("IDCODE", shift_value=0)
            sb.expect_eq(
                "IDCODE during mid-op abort path",
                int(idc) & 0xFFFF_FFFF,
                DTP_DEFAULT_IDCODE,
            )

            # Full TAP reset abort.
            await jtag.reset_tap()
            await ClockCycles(dut.clk_smu_i, 16)
        finally:
            release_forced(forced_otp)

        # Recovery on fabric JTAG2AXI (independent of OTP Force).
        forced_fab = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            st0, r0 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("post-abort VERSION_LO status", st0, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "post-abort VERSION_LO data",
                int(r0) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            st1, r1 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("post-abort sticky VERSION_LO status", st1, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "post-abort sticky VERSION_LO data",
                int(r1) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            sb.expect_eq(
                "post-abort fabric sticky SUCCESS",
                int(capt) & 0x3,
                J2A_STATUS_SUCCESS,
            )
        finally:
            release_forced(forced_fab)

        self.logger.info(
            "smu_dtp_jtag2axi_abort_mid_op_test: IR+TRST abort; VERSION_LO OK"
        )
