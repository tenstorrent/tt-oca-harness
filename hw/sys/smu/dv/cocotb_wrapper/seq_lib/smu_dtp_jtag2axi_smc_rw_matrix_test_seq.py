# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI 1/2/4/8-byte System Bus Access writes on SPM. SEP=1, no Force."""

from __future__ import annotations

import cocotb
from dtp_types import DTP_EXPECTED_DTMCS, unpack_dtmcs
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    smc_addr,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    apply_axi_wstrb,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
DEFAULT_DATA = 0x0123_4567_89AB_CDEF
SIZE_SEED = 0xFEED_FACE_B0B0_CAFE
SIZE_OUTER = 0xA5A5_A5A5_A5A5_A5A5
PARTIAL_EVEN = 0xA5A5_5A5A_C3C3_3C3C
PARTIAL_ODD = 0x5A5A_A5A5_3C3C_C3C3
OTP_POLL = 128
MASK64 = (1 << 64) - 1


def _nbytes(size: int) -> int:
    return 1 << size


def _mask(size: int) -> int:
    return (1 << (8 * _nbytes(size))) - 1


def _full_wstrb(size: int) -> int:
    return (1 << _nbytes(size)) - 1


class smu_dtp_jtag2axi_smc_rw_matrix_test_seq:
    """Access-size and byte-lane matrix on SPM via SMC J2A; gate open on the SEP=1 wrapper."""

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

    async def _wr(self, jtag, addr: int, data: int, *, wstrb: int, size: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=wstrb,
            size=size,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR {name} @0x{addr:08x} size={size} wstrb=0x{wstrb:02x} "
                f"status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(
            f"J2A WR {name} @0x{addr:08x} size={size} wstrb=0x{wstrb:02x} "
            f"data=0x{data:016x} status=SUCCESS"
        )

    async def _rd(self, jtag, addr: int, *, size: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=size,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A RD {name} @0x{addr:08x} size={size} status={st} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & MASK64

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
        sb.expect_eq(
            "CHK-J2A-MATRIX-JTAG-READY",
            idcode,
            DTP_DEFAULT_IDCODE,
            evidence="CHK-J2A-MATRIX-JTAG-READY",
        )

        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        dtmcs = int(await jtag.read("SMC_DTMCS"))
        require_jtag_tdo_resolved("SMC J2A DTMCS")
        if dtmcs != DTP_EXPECTED_DTMCS:
            raise AssertionError(f"SMC J2A DTMCS=0x{dtmcs:08x} want 0x{DTP_EXPECTED_DTMCS:08x}")
        self.s1_ok = True
        self._log(f"CHK-J2A-MATRIX-GATE-OPEN disable={gate} dtmcs=0x{dtmcs:08x}")
        sb.expect_eq(
            "CHK-J2A-MATRIX-GATE-OPEN",
            (gate, dtmcs),
            (0, DTP_EXPECTED_DTMCS),
            evidence="CHK-J2A-MATRIX-GATE-OPEN",
        )

        size_obs: list[tuple[int, int]] = []
        size_want: list[int] = []
        for size in (0, 1, 2, 3):
            addr = SPM + 0x200 + size * 0x10
            window = _mask(size)
            payload = (DEFAULT_DATA ^ (0x1111_1111_1111_1111 * size)) & window
            write_data = (SIZE_OUTER & ~window) | payload
            # The 8-byte read keeps SIZE_SEED outside the access's byte lanes.
            wstrb = _full_wstrb(size)
            want = apply_axi_wstrb(SIZE_SEED, write_data, wstrb, 8)
            await self._wr(
                jtag,
                addr,
                SIZE_SEED,
                wstrb=0xFF,
                size=SMC_DBG_AXSIZE_8B,
                name=f"SIZE{size}-SEED",
            )
            await self._wr(
                jtag,
                addr,
                write_data,
                wstrb=wstrb,
                size=size,
                name=f"SIZE{size}",
            )
            got = await self._rd(jtag, addr, size=SMC_DBG_AXSIZE_8B, name=f"SIZE{size}")
            if got != want:
                raise AssertionError(
                    f"SIZE{size} @0x{addr:08x} want 0x{want:016x} got 0x{got:016x} "
                    f"(WSTRB window must change; outer must stay seed)"
                )
            size_obs.append((size, got))
            size_want.append(want)
            self._log(
                f"CHK-J2A-WSTRB-WIDTH SIZE{size} wstrb=0x{wstrb:02x} "
                f"@0x{addr:08x} data=0x{got:016x}"
            )
        self.s2_ok = True
        sb.expect_eq(
            "CHK-J2A-WSTRB-WIDTH",
            tuple(v for _, v in size_obs),
            tuple(size_want),
            evidence="CHK-J2A-WSTRB-WIDTH",
        )

        # A byte write per set bit of wstrb leaves the beat a single write under
        # wstrb would; System Bus Access issues no other partial strobe.
        partial_obs: list[tuple[int, int]] = []
        for wstrb, tag, pattern, off in (
            (0x55, "even", PARTIAL_EVEN, 0x280),
            (0xAA, "odd", PARTIAL_ODD, 0x290),
        ):
            addr = SPM + off
            await self._wr(
                jtag, addr, 0, wstrb=0xFF, size=SMC_DBG_AXSIZE_8B, name=f"WSTRB-{tag}-CLR"
            )
            for lane in (n for n in range(8) if wstrb >> n & 1):
                await self._wr(
                    jtag,
                    addr + lane,
                    pattern,
                    wstrb=1 << lane,
                    size=0,
                    name=f"WSTRB-{tag}-B{lane}",
                )
            got = await self._rd(jtag, addr, size=SMC_DBG_AXSIZE_8B, name=f"WSTRB-{tag}")
            want = apply_axi_wstrb(0, pattern, wstrb, 8)
            if got != want:
                raise AssertionError(
                    f"WSTRB {tag} @0x{addr:08x} want 0x{want:016x} got 0x{got:016x}"
                )
            partial_obs.append((wstrb, got))
            self._log(
                f"CHK-J2A-MATRIX-WSTRB-{tag} @0x{addr:08x} wstrb=0x{wstrb:02x} data=0x{got:016x}"
            )
        self.s3_ok = True
        sb.expect_eq(
            "CHK-J2A-RW-MATRIX",
            tuple(v for _, v in partial_obs),
            (
                apply_axi_wstrb(0, PARTIAL_EVEN, 0x55, 8),
                apply_axi_wstrb(0, PARTIAL_ODD, 0xAA, 8),
            ),
            evidence="J2A_RW_MATRIX_OK",
        )

        sticky = unpack_dtmcs(int(await jtag.read("SMC_DTMCS")))["dmistat"]
        require_jtag_tdo_resolved("SMC DTMCS dmistat")
        if sticky != 0:
            raise AssertionError(f"SMC DTMCS dmistat={sticky} after matrix, want 0")
        ver_st, ver_data = await jtag2axi_single_read(
            jtag,
            VERSION_LO,
            size=2,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        ver_data &= 0xFFFF_FFFF
        if ver_st != J2A_STATUS_SUCCESS or ver_data != VERSION_LO_RESET:
            raise AssertionError(
                f"VERSION_LO after matrix @0x{VERSION_LO:08x} status={ver_st} "
                f"data=0x{ver_data:08x} want SUCCESS+0x{VERSION_LO_RESET:08x}"
            )
        self.s4_ok = True
        self._log(f"CHK-J2A-MATRIX-STICKY dmistat=0 VERSION_LO=0x{ver_data:08x}")
        sb.expect_eq(
            "CHK-J2A-MATRIX-STICKY",
            (sticky, ver_data),
            (0, VERSION_LO_RESET),
            evidence="CHK-J2A-MATRIX-STICKY",
        )

        self._log(
            f"PASS JTAG2AXI-RW-MATRIX s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} spm=0x{SPM:08x}"
        )
