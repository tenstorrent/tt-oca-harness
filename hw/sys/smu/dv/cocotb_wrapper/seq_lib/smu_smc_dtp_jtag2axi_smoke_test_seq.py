# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC fabric JTAG2AXI smoke: gate open, DTMCS, SCRATCH_15, SPM.

S1: After TCK sync, ``tb_smc_jtag2axi_security_disable`` is 0 and
    ``SMC_DTMCS`` reads the DTMCS value with no sticky DMI status.
S2: 32b write/readback of CPU_CTRL SCRATCH_15 (not SCRATCH_0 —
    that mailbox is the live boot ROM PASS magic).
S3: 64b write/readback of SPM base.

Addresses from ``smc_addr.h``. No Force.

Not claimed: Force-closed gate; OTP J2A; unmapped DECERR.
"""

from __future__ import annotations

import cocotb
from dtp_types import DTP_EXPECTED_DTMCS
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

SCRATCH_15 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 15)
SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SCRATCH_PAT = 0xDEAD_BEEF
SPM_PAT = 0x5A17_C0DE_CAFE_1234
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
        sb.expect_eq(
            "CHK-JTAG2AXI-SMOKE-JTAG-READY",
            idcode,
            DTP_DEFAULT_IDCODE,
            evidence="CHK-JTAG2AXI-SMOKE-JTAG-READY",
        )

        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        dtmcs = int(await jtag.read("SMC_DTMCS"))
        require_jtag_tdo_resolved("SMC J2A DTMCS")
        if dtmcs != DTP_EXPECTED_DTMCS:
            raise AssertionError(f"SMC J2A DTMCS=0x{dtmcs:08x} want 0x{DTP_EXPECTED_DTMCS:08x}")
        self.s1_ok = True
        self._log(f"CHK-JTAG2AXI-SMOKE-GATE-OPEN disable={gate} dtmcs=0x{dtmcs:08x}")
        sb.expect_eq(
            "CHK-JTAG2AXI-SMOKE-GATE-OPEN",
            (gate, dtmcs),
            (0, DTP_EXPECTED_DTMCS),
            evidence="CHK-JTAG2AXI-SMOKE-GATE-OPEN",
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
        sb.expect_eq("CHK-JTAG2AXI-SMOKE-SPM", got_m, SPM_PAT, evidence="CHK-JTAG2AXI-SMOKE-SPM")

        self._log(
            f"PASS JTAG2AXI-SMOKE s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} scratch=0x{SCRATCH_15:08x} "
            f"spm=0x{SPM:08x}"
        )
