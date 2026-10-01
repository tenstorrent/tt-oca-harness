# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC fabric JTAG2AXI smoke: gate open, CAPS, SCRATCH_15, SPM, series INCR.

S1: After TCK sync, ``tb_smc_jtag2axi_security_disable`` is 0 and
    ``SMC_JTAG2AXI_CAPS`` matches the RTL 14-bit packing.
S2: SINGLE_OP 32b write/readback of CPU_CTRL SCRATCH_15 (not SCRATCH_0 —
    that mailbox is the live boot ROM PASS magic).
S3: SINGLE_OP 64b write/readback of SPM base.
S4: Series DATA_INCR write then readback at SPM+0x40 — data match.

Addresses from ``smc_addr.h``. No Force.

Not claimed: Force-closed gate; OTP J2A; unmapped DECERR; NO_INCR /
WITH_ERROR_STATUS series modes.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_JTAG2AXI_CAPS,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_series_incr_read,
    jtag2axi_series_incr_write,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
    smc_series_data_mask,
)

SCRATCH_15 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 15)
SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SERIES_ADDR = SPM + 0x40
SCRATCH_PAT = 0xDEAD_BEEF
SPM_PAT = 0x5A17_C0DE_CAFE_1234
SERIES_PAT = 0x0102_0304_0506_0708
OTP_POLL = 128


class smu_smc_dtp_jtag2axi_smoke_test_seq:
    """SMC fabric J2A smoke; gate open on the SEP=1 wrapper."""

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

    async def _wr32(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR32 {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"J2A WR32 {name} @0x{addr:08x} data=0x{data:08x} status=SUCCESS")

    async def _rd32(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A RD32 {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & 0xFFFF_FFFF

    async def _wr64(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0xFF,
            size=SMC_DBG_AXSIZE_8B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR64 {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"J2A WR64 {name} @0x{addr:08x} data=0x{data:016x} status=SUCCESS")

    async def _rd64(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_8B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A RD64 {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & ((1 << 64) - 1)

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
        sb.expect_eq("CHK-JTAG2AXI-SMOKE-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        caps = int(await jtag.read("SMC_JTAG2AXI_CAPS")) & ((1 << 14) - 1)
        require_jtag_tdo_resolved("SMC J2A CAPS")
        if caps != DTP_EXPECTED_SMC_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SMC J2A CAPS=0x{caps:04x} want 0x{DTP_EXPECTED_SMC_JTAG2AXI_CAPS:04x}"
            )
        self.s1_ok = True
        self._log(f"CHK-JTAG2AXI-SMOKE-GATE-OPEN disable={gate} caps=0x{caps:04x}")
        sb.expect_eq(
            "CHK-JTAG2AXI-SMOKE-GATE-OPEN",
            (gate, caps),
            (0, DTP_EXPECTED_SMC_JTAG2AXI_CAPS),
        )

        await self._wr32(jtag, SCRATCH_15, SCRATCH_PAT, "SCRATCH_15")
        got_s = await self._rd32(jtag, SCRATCH_15, "SCRATCH_15")
        if got_s != SCRATCH_PAT:
            raise AssertionError(f"SCRATCH_15 want 0x{SCRATCH_PAT:08x} got 0x{got_s:08x}")
        self.s2_ok = True
        self._log(f"CHK-JTAG2AXI-SMOKE-SCRATCH @0x{SCRATCH_15:08x} data=0x{got_s:08x}")
        sb.expect_eq(
            "CHK-JTAG2AXI-SMOKE-SCRATCH", got_s, SCRATCH_PAT, evidence="CHK-JTAG2AXI-SMOKE-SCRATCH"
        )

        await self._wr64(jtag, SPM, SPM_PAT, "SPM")
        got_m = await self._rd64(jtag, SPM, "SPM")
        if got_m != SPM_PAT:
            raise AssertionError(f"SPM want 0x{SPM_PAT:016x} got 0x{got_m:016x}")
        self.s3_ok = True
        self._log(f"CHK-JTAG2AXI-SMOKE-SPM @0x{SPM:08x} data=0x{got_m:016x}")
        sb.expect_eq("CHK-JTAG2AXI-SMOKE-SPM", got_m, SPM_PAT)

        mask = smc_series_data_mask(SMC_DBG_AXSIZE_8B)
        want = SERIES_PAT & mask
        wr_st = await jtag2axi_series_incr_write(jtag, SERIES_ADDR, want, poll_limit=OTP_POLL)
        if wr_st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC series INCR WR @0x{SERIES_ADDR:08x} status={wr_st} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        rd_st, got_ser = await jtag2axi_series_incr_read(jtag, SERIES_ADDR, poll_limit=OTP_POLL)
        got_ser &= mask
        if rd_st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC series INCR RD @0x{SERIES_ADDR:08x} status={rd_st} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        if got_ser != want:
            raise AssertionError(
                f"SMC series INCR mismatch @0x{SERIES_ADDR:08x}: "
                f"want 0x{want:016x} got 0x{got_ser:016x}"
            )
        self.s4_ok = True
        self._log(
            f"CHK-JTAG2AXI-SMOKE-SERIES-INCR @0x{SERIES_ADDR:08x} "
            f"data=0x{got_ser:016x} status=SUCCESS"
        )
        sb.expect_eq("CHK-JTAG2AXI-SMOKE-SERIES-INCR", got_ser, want)

        self._log(
            f"PASS JTAG2AXI-SMOKE s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} scratch=0x{SCRATCH_15:08x} "
            f"spm=0x{SPM:08x}"
        )
