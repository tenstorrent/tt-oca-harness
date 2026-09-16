# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP J2A MAP SPARE walk + shadow match. SEP=1, no Force. Not LOCKS."""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    otp_jtag2axi_single_write,
    require_jtag_tdo_resolved,
    shadow_map_word32,
)
from seq_lib.smu_lifecycle_table import LC_STATE_NO_LCC

MAP_BASE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
MAP_SIZE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SIZE")
RESERVED_SYM = "SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR"
# Three distinct SPARE entries; all are 8-byte-aligned (stride 0x20).
RESERVED_IDX = (1, 2, 3)
PATTERNS = (0xA11C_E001, 0xB22D_F112, 0xC33E_0223)
REWRITE0 = 0xD44F_1334
OTP_POLL = 128
MASK32 = 0xFFFF_FFFF


def _reserved_addrs() -> tuple[int, ...]:
    addrs = tuple(smc_indexed_addr(RESERVED_SYM, i) for i in RESERVED_IDX)
    end = MAP_BASE + MAP_SIZE
    for addr in addrs:
        if not (MAP_BASE <= addr < end):
            raise RuntimeError(f"SPARE 0x{addr:08x} not in MAP [0x{MAP_BASE:08x}, 0x{end:08x})")
        if addr & 7:
            raise RuntimeError(f"SPARE 0x{addr:08x} is not 8-byte aligned")
    return addrs


RESERVED_ADDRS = _reserved_addrs()


class smu_dtp_otp_smc_complete_rw_test_seq:
    """OTP+fabric+shadow MAP walk on SPARE words; gate open on the SEP=1 wrapper."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False

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

    async def _otp_wr(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await otp_jtag2axi_single_write(
            jtag, addr, data, poll_limit=OTP_POLL, require_complete=True
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"OTP J2A WR {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"OTP J2A WR {name} @0x{addr:08x} data=0x{data:08x} status=SUCCESS")

    async def _otp_rd(self, jtag, addr: int, name: str) -> int:
        st, rdata = await otp_jtag2axi_single_read(
            jtag, addr, poll_limit=OTP_POLL, require_complete=True
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"OTP J2A RD {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & MASK32

    async def _fab_rd(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"fabric MAP RD {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"fabric J2A RD {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & MASK32

    def _shadow(self, addr: int, name: str) -> int:
        off = addr - MAP_BASE
        shadow = shadow_map_word32(self.dut, off)
        if shadow is None:
            raise AssertionError(
                f"{name} shadow_map_word32 returned None "
                f"(smc_shadow_regs missing or unreadable) off=0x{off:x}"
            )
        return int(shadow) & MASK32

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
        sb.expect_eq("CHK-OTP-COMPLETE-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

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
        self._log(f"CHK-OTP-COMPLETE-GATE-OPEN disable={gate} lc=0x{lc:02x} sigint={sigint}")
        sb.expect_eq(
            "CHK-OTP-COMPLETE-GATE-OPEN",
            (gate, lc, sigint),
            (0, LC_STATE_NO_LCC, 0),
        )

        for addr, pat, idx in zip(RESERVED_ADDRS, PATTERNS, RESERVED_IDX):
            await self._otp_wr(jtag, addr, pat, f"RES{idx}")
        self.s2_ok = True

        trip: list[tuple[int, int, int]] = []
        for addr, pat, idx in zip(RESERVED_ADDRS, PATTERNS, RESERVED_IDX):
            otp = await self._otp_rd(jtag, addr, f"RES{idx}")
            fab = await self._fab_rd(jtag, addr, f"RES{idx}")
            shadow = self._shadow(addr, f"RES{idx}")
            if otp != pat or fab != pat or shadow != pat:
                raise AssertionError(
                    f"RES{idx} @0x{addr:08x} want 0x{pat:08x} "
                    f"otp=0x{otp:08x} fab=0x{fab:08x} shadow=0x{shadow:08x}"
                )
            trip.append((otp, fab, shadow))
            self._log(f"CHK-OTP-MAP-RW RES{idx} @0x{addr:08x} otp=fab=shadow=0x{pat:08x}")
        self.s3_ok = True
        sb.expect_eq(
            "CHK-OTP-MAP-RW",
            tuple(trip),
            tuple((p, p, p) for p in PATTERNS),
        )

        await self._otp_wr(jtag, RESERVED_ADDRS[0], REWRITE0, "RES0-RE")
        got0 = await self._otp_rd(jtag, RESERVED_ADDRS[0], "RES0-RE")
        if got0 != REWRITE0:
            raise AssertionError(f"RES0 rewrite want 0x{REWRITE0:08x} got 0x{got0:08x}")
        hold: list[int] = []
        for addr, pat, idx in zip(RESERVED_ADDRS[1:], PATTERNS[1:], RESERVED_IDX[1:]):
            got = await self._otp_rd(jtag, addr, f"RES{idx}-HOLD")
            if got != pat:
                raise AssertionError(
                    f"RES{idx} isolation fail: want 0x{pat:08x} got 0x{got:08x} after RES0 rewrite"
                )
            hold.append(got)
        self.s4_ok = True
        sb.expect_eq(
            "CHK-OTP-MAP-ISOLATE",
            (got0, tuple(hold)),
            (REWRITE0, PATTERNS[1:]),
        )

        self._log(
            f"PASS DTP-OTP-SMC-COMPLETE-RW s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} "
            f"res=[{', '.join(f'0x{a:08x}' for a in RESERVED_ADDRS)}]"
        )
