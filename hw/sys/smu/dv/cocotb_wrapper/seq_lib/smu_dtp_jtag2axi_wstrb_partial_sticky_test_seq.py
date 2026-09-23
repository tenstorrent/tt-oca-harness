# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI partial WSTRB on SPM; neighbor word unchanged. SEP=1, no Force."""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_JTAG2AXI_CAPS,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    apply_axi_wstrb,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
WORD_A = SPM + 0x300
WORD_B = SPM + 0x308
SEED_A = 0x1111_2222_3333_4444
SEED_B = 0xAAAA_BBBB_CCCC_DDDD
PARTIAL = 0xFFFF_0000_FFFF_0000
WSTRB = 0x55
OTP_POLL = 128
MASK64 = (1 << 64) - 1


class smu_dtp_jtag2axi_wstrb_partial_sticky_test_seq:
    """Partial WSTRB merge with adjacent SPM word isolation; no Force."""

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

    async def _wr64(self, jtag, addr: int, data: int, *, wstrb: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_8B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR {name} @0x{addr:08x} wstrb=0x{wstrb:02x} status={st} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(
            f"J2A WR {name} @0x{addr:08x} wstrb=0x{wstrb:02x} data=0x{data:016x} status=SUCCESS"
        )

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
                f"J2A RD {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
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
        sb.expect_eq("CHK-J2A-WSTRB-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

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
        self._log(f"CHK-J2A-WSTRB-GATE-OPEN disable={gate} caps=0x{caps:04x}")
        sb.expect_eq(
            "CHK-J2A-WSTRB-GATE-OPEN",
            (gate, caps),
            (0, DTP_EXPECTED_SMC_JTAG2AXI_CAPS),
        )

        await self._wr64(jtag, WORD_A, SEED_A, wstrb=0xFF, name="SEED-A")
        await self._wr64(jtag, WORD_B, SEED_B, wstrb=0xFF, name="SEED-B")
        got_a0 = await self._rd64(jtag, WORD_A, "SEED-A")
        got_b0 = await self._rd64(jtag, WORD_B, "SEED-B")
        if got_a0 != SEED_A or got_b0 != SEED_B:
            raise AssertionError(
                f"seed mismatch A=0x{got_a0:016x} want 0x{SEED_A:016x} "
                f"B=0x{got_b0:016x} want 0x{SEED_B:016x}"
            )
        self.s2_ok = True
        self._log(
            f"CHK-J2A-WSTRB-SEED A@0x{WORD_A:08x}=0x{got_a0:016x} B@0x{WORD_B:08x}=0x{got_b0:016x}"
        )
        sb.expect_eq("CHK-J2A-WSTRB-SEED", (got_a0, got_b0), (SEED_A, SEED_B))

        await self._wr64(jtag, WORD_A, PARTIAL, wstrb=WSTRB, name="PARTIAL-A")
        got_a = await self._rd64(jtag, WORD_A, "PARTIAL-A")
        got_b = await self._rd64(jtag, WORD_B, "NEIGHBOR-B")
        want_a = apply_axi_wstrb(SEED_A, PARTIAL, WSTRB, 8)
        if got_a != want_a:
            raise AssertionError(
                f"partial A @0x{WORD_A:08x} want 0x{want_a:016x} got 0x{got_a:016x}"
            )
        if got_b != SEED_B:
            raise AssertionError(
                f"neighbor B @0x{WORD_B:08x} changed: want 0x{SEED_B:016x} got 0x{got_b:016x}"
            )
        self.s3_ok = True
        self._log(f"CHK-J2A-WSTRB-NBR A=0x{got_a:016x} B=0x{got_b:016x} wstrb=0x{WSTRB:02x}")
        sb.expect_eq(
            "CHK-J2A-WSTRB-NBR", (got_a, got_b), (want_a, SEED_B), evidence="J2A_WSTRB_NEIGHBOR"
        )

        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved("SMC SINGLE_OP sticky")
        sticky = int(capt) & 0x3
        if sticky == J2A_STATUS_BUSY:
            raise AssertionError("SINGLE_OP sticky BUSY after partial WSTRB")
        if sticky != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SINGLE_OP sticky status={sticky} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self.s4_ok = True
        self._log("CHK-J2A-WSTRB-STICKY status=SUCCESS")
        sb.expect_eq("CHK-J2A-WSTRB-STICKY", sticky, J2A_STATUS_SUCCESS)

        self._log(
            f"PASS JTAG2AXI-WSTRB-NBR s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} a=0x{WORD_A:08x} b=0x{WORD_B:08x}"
        )
