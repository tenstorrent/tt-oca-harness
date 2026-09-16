# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OTP JTAG2AXI series NO_INCR R/W + MAP-CTRL hole SLVERR (SEP=1, no Force).

S1: After TCK sync, ``tb_otp_jtag2axi_security_disable`` reads 0 -- the OTP
    J2A gate is open in this configuration. ``lc_state_o`` is the no-LCC word
    of ``seq_lib.smu_lifecycle_table``, so the eFuse JTAG demux is not
    err_slv.
S2: Series NO_INCR write PATTERN_A to MAP SPARE[0], then series NO_INCR readback
    OKAY + data match.
S3: SINGLE_OP read of SPARE[0] (same IR as the hole) returns SUCCESS + PATTERN_A;
    SINGLE_OP read of MAP_BASE+MAP_SIZE (below CTRL) returns SLVERR +
    ``0xbadcab1e``; SINGLE_OP re-read of SPARE[0] still SUCCESS + PATTERN_A.

SPARE[0] from ``smc_addr.h`` ``SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(0)``.
Hole from ``SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR + SMC_TOP_SMC_EFUSE_MAP_SIZE``.

Not claimed: Force-closed gate; SEP OTP; INCR across MAP fields; SHIM-unmapped
DECERR at 0xC000D000 (needs a real eFuse SHIM or TB err_slv).
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_OTP_ERR_DECODE_DATA,
    make_smu_jtag_tap,
    otp_jtag2axi_series_no_incr_read,
    otp_jtag2axi_series_no_incr_write,
    otp_jtag2axi_single_read,
    otp_series_data_mask,
)
from seq_lib.smu_lifecycle_table import LC_STATE_NO_LCC

SPARE0 = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)
MAP_BASE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
MAP_SIZE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SIZE")
CTRL_BASE = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR")
HOLE = MAP_BASE + MAP_SIZE
if not (MAP_BASE < HOLE < CTRL_BASE):
    raise RuntimeError(
        f"MAP-CTRL hole 0x{HOLE:08x} not strictly between MAP 0x{MAP_BASE:08x} "
        f"and CTRL 0x{CTRL_BASE:08x}"
    )
PATTERN_A = 0xA5A5_5A5A
OTP_POLL = 128


class smu_dtp_otp_smc_series_error_test_seq:
    """OTP J2A series NO_INCR allow-path + MAP-CTRL hole SLVERR; no Force."""

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

    async def _single_rd(self, jtag, addr: int, name: str) -> tuple[int, int]:
        st, rdata = await otp_jtag2axi_single_read(
            jtag, addr, poll_limit=OTP_POLL, require_complete=True
        )
        return st, int(rdata) & 0xFFFF_FFFF

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-OTP-SMC-SERIES-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        gate = self._sample_int("tb_otp_jtag2axi_security_disable") & 1
        lc = self._sample_int("lc_state_o") & 0xFF
        sigint = self._sample_int("lc_sigint_err_o") & 1
        if gate != 0:
            raise AssertionError(f"OTP J2A still gated after TCK sync: security_disable={gate}")
        if lc != LC_STATE_NO_LCC:
            raise AssertionError(
                f"lc_state_o=0x{lc:02x} want 0x{LC_STATE_NO_LCC:02x} "
                "(PROD would steer eFuse JTAG demux to err_slv)"
            )
        if sigint != 0:
            raise AssertionError(f"lc_sigint_err_o={sigint} want 0 (demux err_slv)")
        self.s1_ok = True
        self._log(f"CHK-OTP-SMC-SERIES-GATE-OPEN disable={gate} lc=0x{lc:02x} sigint={sigint}")
        sb.expect_eq("CHK-OTP-SMC-SERIES-GATE-OPEN", gate, 0)

        mask = otp_series_data_mask()
        want = PATTERN_A & mask
        wr_st = await otp_jtag2axi_series_no_incr_write(jtag, SPARE0, want, poll_limit=OTP_POLL)
        if wr_st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"OTP series WR @0x{SPARE0:08x} status={wr_st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        rd_st, got = await otp_jtag2axi_series_no_incr_read(jtag, SPARE0, poll_limit=OTP_POLL)
        got &= mask
        if rd_st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"OTP series RD @0x{SPARE0:08x} status={rd_st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        if got != want:
            raise AssertionError(
                f"OTP series mismatch @0x{SPARE0:08x}: want 0x{want:08x} got 0x{got:08x}"
            )
        self.s2_ok = True
        self._log(f"CHK-OTP-SMC-SERIES-RW @0x{SPARE0:08x} data=0x{got:08x} status=SUCCESS")
        sb.expect_eq("CHK-OTP-SMC-SERIES-RW", got, want)

        allow_st, allow_data = await self._single_rd(jtag, SPARE0, "SPARE0-ALLOW")
        if allow_st != J2A_STATUS_SUCCESS or allow_data != want:
            raise AssertionError(
                f"OTP SINGLE_OP SPARE0 allow @0x{SPARE0:08x} status={allow_st} "
                f"data=0x{allow_data:08x} want SUCCESS+0x{want:08x}"
            )
        self._log(
            f"CHK-OTP-SMC-SINGLE-OP-ALLOW @0x{SPARE0:08x} data=0x{allow_data:08x} status=SUCCESS"
        )
        sb.expect_eq("CHK-OTP-SMC-SINGLE-OP-ALLOW", allow_data, want)

        hole_st, hole_data = await self._single_rd(jtag, HOLE, "HOLE")
        if hole_st == J2A_STATUS_SUCCESS:
            raise AssertionError(f"OTP decode hole @0x{HOLE:08x} returned OKAY")
        if hole_st != J2A_STATUS_SLVERR:
            raise AssertionError(
                f"OTP decode hole @0x{HOLE:08x} status={hole_st} want SLVERR={J2A_STATUS_SLVERR}"
            )
        if hole_data != SMC_OTP_ERR_DECODE_DATA:
            raise AssertionError(
                f"OTP decode hole @0x{HOLE:08x} data=0x{hole_data:08x} "
                f"want 0x{SMC_OTP_ERR_DECODE_DATA:08x}"
            )
        self._log(f"CHK-OTP-SMC-DECODE-SLVERR @0x{HOLE:08x} status=SLVERR data=0x{hole_data:08x}")
        sb.expect_eq(
            "CHK-OTP-SMC-DECODE-SLVERR",
            (hole_st, hole_data),
            (J2A_STATUS_SLVERR, SMC_OTP_ERR_DECODE_DATA),
        )

        stab_st, stab_data = await self._single_rd(jtag, SPARE0, "SPARE0-STABLE")
        if stab_st != J2A_STATUS_SUCCESS or stab_data != want:
            raise AssertionError(
                f"OTP SINGLE_OP SPARE0 after hole @0x{SPARE0:08x} status={stab_st} "
                f"data=0x{stab_data:08x} want SUCCESS+0x{want:08x}"
            )
        self.s3_ok = True
        self._log(
            f"CHK-OTP-SMC-SPARE-STABLE @0x{SPARE0:08x} data=0x{stab_data:08x} "
            f"status=SUCCESS hole=0x{HOLE:08x}"
        )
        sb.expect_eq("CHK-OTP-SMC-SPARE-STABLE", stab_data, want)

        self._log(
            f"PASS DTP-OTP-SMC-SERIES-ERROR s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} spare0=0x{SPARE0:08x} hole=0x{HOLE:08x}"
        )
