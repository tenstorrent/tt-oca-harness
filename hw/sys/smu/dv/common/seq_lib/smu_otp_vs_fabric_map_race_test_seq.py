# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP vs fabric J2A MAP SPARE[0] race; last writer wins, no tear. SEP=0, no Force."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_OTP_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    pack_otp_single_op,
    require_jtag_tdo_resolved,
    shadow_map_word32,
    unpack_otp_single_op,
)

SPARE0 = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)
MAP_BASE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
MAP_BYTE_OFF = SPARE0 - MAP_BASE
PAT_O = 0x0A70_AAA1
PAT_F = 0xFAB0_BBB2
PINGPONG = 4
OTP_POLL = 128
SEP0_LC_STATE = 0xF0


class smu_otp_vs_fabric_map_race_test_seq:
    """OTP vs fabric MAP race: coherent winner, no silent tear."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _poll_otp_status(self, jtag, poll_limit: int = OTP_POLL) -> int:
        status = J2A_STATUS_BUSY
        for _ in range(poll_limit):
            capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
            require_jtag_tdo_resolved("OTP race poll")
            status, _ = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                return status
            await ClockCycles(self.dut.clk_smu_i, 16)
        return status

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        otp_gate = self._sample_int("tb_otp_jtag2axi_security_disable") & 1
        fab_gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        lc = self._sample_int("lc_state_o") & 0xFF
        if otp_gate != 0 or fab_gate != 0:
            raise AssertionError(f"J2A gated after TCK: otp={otp_gate} fab={fab_gate}")
        if lc != SEP0_LC_STATE:
            raise AssertionError(f"lc_state_o=0x{lc:02x} want 0x{SEP0_LC_STATE:02x}")
        self.s1_ok = True
        sb.expect_eq("CHK-OTPFAB-GATE-OPEN", (otp_gate, fab_gate), (0, 0))

        raw_o = pack_otp_single_op(
            J2A_OP_WRITE,
            SPARE0,
            PAT_O,
            wstrb=0xF,
            size=SMC_OTP_AXSIZE_4B,
        )
        await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw_o)
        require_jtag_tdo_resolved("OTP overlap kick")
        st_f, _ = await jtag2axi_single_write(
            jtag,
            SPARE0,
            PAT_F,
            wstrb=0xF,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved("fabric overlap write")
        if st_f != J2A_STATUS_SUCCESS:
            raise AssertionError(f"overlap fabric write status={st_f}")
        st_o = await self._poll_otp_status(jtag)
        if st_o == J2A_STATUS_BUSY:
            raise AssertionError("overlap OTP stuck BUSY")
        sb.expect_eq("CHK-OTPFAB-OVERLAP-FAB", st_f, J2A_STATUS_SUCCESS)

        await ClockCycles(dut.clk_smu_i, 32)
        st_or, ord_ = await otp_jtag2axi_single_read(
            jtag, SPARE0, require_complete=True, poll_limit=OTP_POLL
        )
        require_jtag_tdo_resolved("overlap OTP read")
        st_fr, frd = await jtag2axi_single_read(
            jtag,
            SPARE0,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved("overlap fabric read")
        if st_or != J2A_STATUS_SUCCESS or st_fr != J2A_STATUS_SUCCESS:
            raise AssertionError(f"overlap read OTP st={st_or} fabric st={st_fr}")
        o_val = int(ord_) & 0xFFFF_FFFF
        f_val = int(frd) & 0xFFFF_FFFF
        if o_val != f_val:
            raise AssertionError(f"overlap OTP=0x{o_val:08x} fabric=0x{f_val:08x} disagree")
        if o_val not in (PAT_O, PAT_F):
            raise AssertionError(f"overlap tear: got 0x{o_val:08x}")
        shadow = shadow_map_word32(dut, MAP_BYTE_OFF)
        if shadow is None:
            raise AssertionError(
                "overlap shadow_map_word32 returned None (smc_shadow_regs missing or unreadable)"
            )
        if shadow != o_val:
            raise AssertionError(f"overlap shadow=0x{shadow:08x} != readback 0x{o_val:08x}")
        self.s2_ok = True
        self._log(
            f"OTPFAB overlap winner=0x{o_val:08x} shadow=0x{shadow:08x} "
            f"spare0=0x{SPARE0:08x} off=0x{MAP_BYTE_OFF:x}"
        )
        sb.expect_eq("CHK-OTPFAB-OVERLAP-COHERENT", o_val, f_val)
        sb.expect_eq("CHK-OTPFAB-OVERLAP-SHADOW", shadow, o_val)

        last = o_val
        for i in range(PINGPONG):
            if i % 2 == 0:
                pat = PAT_O ^ (i << 8)
                st, _ = await jtag2axi_single_write(
                    jtag,
                    SPARE0,
                    pat,
                    wstrb=0xF,
                    size=SMC_DBG_AXSIZE_4B,
                    require_complete=True,
                )
                require_jtag_tdo_resolved(f"pingpong fabric[{i}]")
                if st != J2A_STATUS_SUCCESS:
                    raise AssertionError(f"pingpong fabric[{i}] status={st}")
            else:
                pat = PAT_F ^ (i << 8)
                raw = pack_otp_single_op(
                    J2A_OP_WRITE,
                    SPARE0,
                    pat,
                    wstrb=0xF,
                    size=SMC_OTP_AXSIZE_4B,
                )
                await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
                require_jtag_tdo_resolved(f"pingpong OTP[{i}] kick")
                st = await self._poll_otp_status(jtag)
                if st != J2A_STATUS_SUCCESS:
                    raise AssertionError(f"pingpong OTP[{i}] status={st}")
            last = pat

        st_r, rb = await jtag2axi_single_read(
            jtag,
            SPARE0,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved("pingpong fabric final")
        if st_r != J2A_STATUS_SUCCESS:
            raise AssertionError(f"pingpong fabric read status={st_r}")
        got = int(rb) & 0xFFFF_FFFF
        if got != last:
            raise AssertionError(f"pingpong last-writer want 0x{last:08x} got 0x{got:08x}")
        st_or2, ord2 = await otp_jtag2axi_single_read(
            jtag, SPARE0, require_complete=True, poll_limit=OTP_POLL
        )
        if st_or2 != J2A_STATUS_SUCCESS or (int(ord2) & 0xFFFF_FFFF) != last:
            raise AssertionError(
                f"pingpong OTP final st={st_or2} data=0x{int(ord2):08x} want 0x{last:08x}"
            )
        shadow2 = shadow_map_word32(dut, MAP_BYTE_OFF)
        if shadow2 is None:
            raise AssertionError(
                "pingpong shadow_map_word32 returned None (smc_shadow_regs missing or unreadable)"
            )
        if shadow2 != last:
            raise AssertionError(f"pingpong shadow=0x{shadow2:08x} != last 0x{last:08x}")
        self.s3_ok = True
        self._log(f"CHK-OTPFAB-PINGPONG last=0x{last:08x} shadow=0x{shadow2:08x}")
        sb.expect_eq("CHK-OTPFAB-PINGPONG", got, last)
        sb.expect_eq(
            "CHK-RACE-OTP-FAB shadow==last-writer",
            shadow2,
            last,
            evidence="RACE_OTP_FABRIC",
        )
