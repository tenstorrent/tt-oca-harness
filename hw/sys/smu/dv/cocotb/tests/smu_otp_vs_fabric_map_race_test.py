# SPDX-License-Identifier: Apache-2.0
"""smu_otp_vs_fabric_map_race_test - P3-H3b OTP || fabric MAP race (G4).

Same TAP serializes IR, so race is created by kicking OTP write then immediately
issuing fabric write (OTP AXI may still be outstanding), plus a ping-pong burst:

  1. Kick OTP write PAT_O; before poll, fabric write PAT_F to same MAP abs
  2. Poll both paths to completion
  3. Shadow + OTP read + fabric read all agree; value in {PAT_O, PAT_F}
  4. Ping-pong N alternated commits; final == last writer; no tear

Must FAIL if shadow silent-tears or paths disagree after settle.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_EFUSE_MAP_BIRA_WORD,
    SMC_OTP_AXSIZE_4B,
    force_otp_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    pack_otp_single_op,
    release_forced,
    shadow_map_word32,
    unpack_otp_single_op,
    unpack_single_op,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

PAT_O = 0x0A70_AAA1
PAT_F = 0xFAB0_BBB2
MAP_BYTE_OFF = SMC_EFUSE_MAP_BIRA_WORD & 0xFFF
PINGPONG = 4


async def _poll_otp_status(jtag, poll_limit: int = 128) -> int:
    status = J2A_STATUS_BUSY
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
        status, _ = unpack_otp_single_op(capt)
        if status != J2A_STATUS_BUSY:
            return status
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    return status


async def _poll_fab_status(jtag, poll_limit: int = 128) -> int:
    status = J2A_STATUS_BUSY
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        status, _ = unpack_single_op(capt)
        if status != J2A_STATUS_BUSY:
            return status
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    return status


@pyuvm.test()
class smu_otp_vs_fabric_map_race_test(smu_base_test):
    """OTP vs fabric MAP race: coherent winner, no silent tear."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        forced = force_otp_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            # --- Overlapped kick: OTP then immediate fabric ---
            raw_o = pack_otp_single_op(
                J2A_OP_WRITE,
                SMC_EFUSE_MAP_BIRA_WORD,
                PAT_O,
                wstrb=0xF,
                size=SMC_OTP_AXSIZE_4B,
            )
            await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw_o)
            # Do not wait for OTP AXI complete; switch to fabric writer.
            st_f, _ = await jtag2axi_single_write(
                jtag,
                SMC_EFUSE_MAP_BIRA_WORD,
                PAT_F,
                wstrb=0xF,
                size=SMC_DBG_AXSIZE_4B,
            )
            sb.expect_eq("overlap fabric write status", st_f, J2A_STATUS_SUCCESS, evidence="RACE_OTP_FABRIC")
            st_o = await _poll_otp_status(jtag)
            sb.expect_true(
                f"overlap OTP completed (st={st_o})",
                st_o != J2A_STATUS_BUSY,
            )

            await ClockCycles(dut.clk_smu_i, 32)
            shadow = shadow_map_word32(dut, MAP_BYTE_OFF)
            assert shadow is not None, "smc_shadow_regs not VPI-readable"
            sb.expect_true(
                f"overlap shadow is a winner (0x{shadow:08x})",
                shadow in (PAT_O, PAT_F),
            )

            st_or, ord_ = await otp_jtag2axi_single_read(jtag, SMC_EFUSE_MAP_BIRA_WORD)
            sb.expect_eq("overlap OTP read status", st_or, J2A_STATUS_SUCCESS)
            st_fr, frd = await jtag2axi_single_read(
                jtag, SMC_EFUSE_MAP_BIRA_WORD, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("overlap fabric read status", st_fr, J2A_STATUS_SUCCESS)
            o_val = int(ord_) & 0xFFFF_FFFF
            f_val = int(frd) & 0xFFFF_FFFF
            sb.expect_eq("overlap OTP==fabric readback", o_val, f_val)
            sb.expect_eq("overlap readback==shadow", o_val, shadow)

            # --- Ping-pong: last writer wins ---
            last = shadow
            for i in range(PINGPONG):
                if i % 2 == 0:
                    pat = PAT_O ^ (i << 8)
                    st, _ = await jtag2axi_single_write(
                        jtag,
                        SMC_EFUSE_MAP_BIRA_WORD,
                        pat,
                        wstrb=0xF,
                        size=SMC_DBG_AXSIZE_4B,
                    )
                    sb.expect_eq(f"pingpong fabric[{i}] status", st, J2A_STATUS_SUCCESS)
                else:
                    pat = PAT_F ^ (i << 8)
                    raw = pack_otp_single_op(
                        J2A_OP_WRITE,
                        SMC_EFUSE_MAP_BIRA_WORD,
                        pat,
                        wstrb=0xF,
                        size=SMC_OTP_AXSIZE_4B,
                    )
                    await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
                    await ClockCycles(dut.clk_smu_i, 32)
                    st = await _poll_otp_status(jtag)
                    sb.expect_eq(f"pingpong OTP[{i}] status", st, J2A_STATUS_SUCCESS)
                last = pat

            shadow2 = shadow_map_word32(dut, MAP_BYTE_OFF)
            assert shadow2 is not None
            sb.expect_eq("pingpong shadow == last writer", shadow2, last)
            st_r, rb = await jtag2axi_single_read(
                jtag, SMC_EFUSE_MAP_BIRA_WORD, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("pingpong fabric read status", st_r, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "pingpong fabric == last",
                int(rb) & 0xFFFF_FFFF,
                last,
            )
        finally:
            release_forced(forced)

        self.logger.info("smu_otp_vs_fabric_map_race_test: overlap+pingpong OK")
