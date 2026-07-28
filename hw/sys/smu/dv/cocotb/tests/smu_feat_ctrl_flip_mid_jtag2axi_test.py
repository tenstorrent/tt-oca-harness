# SPDX-License-Identifier: Apache-2.0
"""smu_feat_ctrl_flip_mid_jtag2axi_test - P3-H4a feat_ctrl flip mid-BUSY.

OTP ungated probe stays BUSY (no bank). Mid-transaction gate (clear fuse_test)
must not deliver SUCCESS+silicon data. In-flight may stick BUSY (already
started); prove gate with TRST + fresh gated op that must leave BUSY:

  1. Enable OTP; start probe; confirm BUSY
  2. Force-clear fuse_test mid-BUSY
  3. In-flight must not become SUCCESS+VERSION_LO
  4. TRST; fresh gated OTP op leaves BUSY (bounded)
  5. Re-enable fabric; VERSION_LO SUCCESS

Must FAIL if SUCCESS+good after gate or fresh gated op hangs BUSY.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_OP_READ,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_OTP_AXSIZE_4B,
    SMC_OTP_DEFAULT_PROBE_ADDR,
    force_jtag2axi_lifecycle_enable,
    force_otp_jtag2axi_lifecycle_disable,
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
class smu_feat_ctrl_flip_mid_jtag2axi_test(smu_base_test):
    """Clear feat_ctrl mid-BUSY; gated idle bounded; fabric recovers."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        forced_en = force_otp_jtag2axi_lifecycle_enable(dut, self.logger)
        forced_gate = None
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
            sb.expect_true("OTP BUSY before mid-op gate flip", busy_seen)

            forced_gate = force_otp_jtag2axi_lifecycle_disable(dut, self.logger)
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(4):
                await jtag.step_tms(0)

            # In-flight may remain BUSY; must not silently become SUCCESS+silicon.
            capt_mid = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
            st_mid, data_mid = unpack_otp_single_op(capt_mid)
            good_mid = (
                st_mid == J2A_STATUS_SUCCESS
                and (int(data_mid) & 0xFFFF_FFFF) == VERSION_LO_EXPECT
            )
            sb.expect_true(
                "mid-op gate: in-flight not SUCCESS+VERSION_LO",
                not good_mid,
            )
            self.logger.info(
                "in-flight after gate status=%s data=0x%08x",
                st_mid,
                int(data_mid) & 0xFFFF_FFFF,
            )

            # Clear sticky BUSY via TRST; prove gate with fresh idle completion.
            await jtag.reset_tap()
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(4):
                await jtag.step_tms(0)

            await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
            await ClockCycles(dut.clk_smu_i, 32)
            left_busy = False
            final_st = J2A_STATUS_BUSY
            for _ in range(16):
                capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
                final_st, _ = unpack_otp_single_op(capt)
                if final_st != J2A_STATUS_BUSY:
                    left_busy = True
                    break
                await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_true(
                f"post-gate fresh OTP leaves BUSY (st={final_st})",
                left_busy,
            )
        finally:
            if forced_gate is not None:
                release_forced(forced_gate)
            release_forced(forced_en)

        forced_fab = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)
            st, rdata = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("post-gate VERSION_LO status", st, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "post-gate VERSION_LO data",
                int(rdata) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
        finally:
            release_forced(forced_fab)

        self.logger.info(
            "smu_feat_ctrl_flip_mid_jtag2axi_test: mid-BUSY gate + recover OK"
        )
