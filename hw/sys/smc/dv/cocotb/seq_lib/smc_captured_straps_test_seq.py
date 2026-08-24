# SPDX-License-Identifier: Apache-2.0
"""captured_straps_i to STRAPS_LO/HI. Does not claim pad latch or boot-ROM decode."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

STRAPS_LO = smc_addr("SMC_TOP_SMC_RESET_UNIT_STRAPS_LO_BASE_ADDR")
STRAPS_HI = smc_addr("SMC_TOP_SMC_RESET_UNIT_STRAPS_HI_BASE_ADDR")
HI_MASK = reset_unit_u32("RESET_UNIT__STRAPS_HI__STRAPS_bm")

# Distinct non-zero patterns in the 61 bonded bits (HI is 29 bits).
_LO_A = 0xA5A55A5A
_HI_A = 0x15555555
_LO_B = 0x5A5AA5A5
_HI_B = 0x0AAAAAAA
_CSR_BOUND = 64


def _pack(lo: int, hi: int) -> int:
    return ((hi & HI_MASK) << 32) | (lo & 0xFFFFFFFF)


class smc_captured_straps_test_seq(SmcCsrSeq):
    """Drive captured_straps_i; STRAPS_LO/HI must follow 0 → A → B."""

    def __init__(self, name: str = "smc_captured_straps_test_seq") -> None:
        super().__init__(name)
        self.idle_ok = False
        self.pat_a_ok = False
        self.pat_b_ok = False

    async def _await_straps(self, want_lo: int, want_hi: int, label: str) -> tuple[int, int]:
        last_lo = last_hi = None
        for _ in range(_CSR_BOUND):
            last_lo = await self.csr_read(f"{label}_LO", STRAPS_LO)
            last_hi = await self.csr_read(f"{label}_HI", STRAPS_HI)
            if last_lo == want_lo and (last_hi & HI_MASK) == want_hi:
                return last_lo, last_hi
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: STRAPS last lo=0x{last_lo:x} hi=0x{last_hi:x} "
            f"want lo=0x{want_lo:x} hi=0x{want_hi:x} after {_CSR_BOUND} polls"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_captured_straps"), "tb_captured_straps missing"
        assert HI_MASK == 0x1FFFFFFF, f"STRAPS_HI mask drifted: 0x{HI_MASK:x}"

        dut.tb_captured_straps.value = 0
        lo0, hi0 = await self._await_straps(0, 0, "IDLE")
        self.idle_ok = True
        cocotb.log.info(
            "CHK-STRAP-IDLE: STRAPS_LO=0x%x STRAPS_HI=0x%x pin=0", lo0, hi0
        )

        dut.tb_captured_straps.value = _pack(_LO_A, _HI_A)
        lo1, hi1 = await self._await_straps(_LO_A, _HI_A, "PAT_A")
        self.pat_a_ok = True
        cocotb.log.info(
            "CHK-STRAP-A: STRAPS_LO=0x%x STRAPS_HI=0x%x pin=0x%x",
            lo1,
            hi1,
            _pack(_LO_A, _HI_A),
        )

        dut.tb_captured_straps.value = _pack(_LO_B, _HI_B)
        lo2, hi2 = await self._await_straps(_LO_B, _HI_B, "PAT_B")
        self.pat_b_ok = True
        cocotb.log.info(
            "CHK-STRAP-B: STRAPS_LO=0x%x STRAPS_HI=0x%x pin=0x%x",
            lo2,
            hi2,
            _pack(_LO_B, _HI_B),
        )
        cocotb.log.info(
            "CHK-STRAP-BASIC: idle=%s a=%s b=%s",
            self.idle_ok,
            self.pat_a_ok,
            self.pat_b_ok,
        )
