# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""COLD vs COLD_WARM scratch across tb_sep_wdt_reset_n. No Force."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
COLD_PAT = 0xDEADBEEF
WARM_PAT = 0xCAFEB0BA
# WDT reset into the COLD_WARM domain is async; 16 SMC clocks cover the
# wrapper sync into rst_wdt. Proof is the post-pulse CSR handshake, not this
# pulse width alone.
_WDT_PULSE = 16
_CSR_BOUND = 64


class smc_reset_unit_sanity_test_seq(SmcCsrSeq):
    """COLD persists across SEP WDT reset; COLD_WARM does not."""

    def __init__(self, name: str = "smc_reset_unit_sanity_test_seq") -> None:
        super().__init__(name)
        self.pre_ok = False
        self.cold_ok = False
        self.warm_ok = False

    async def _await_warm_cleared(self, dut, label: str) -> int:
        last = None
        for _ in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_WARM", SCRATCH_COLD_WARM_0)
            if last == 0:
                return last
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(f"{label}: COLD_WARM last=0x{last:x} want=0 after {_CSR_BOUND} polls")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert int(dut.tb_sep_wdt_reset_n.value) == 1, "SEP WDT reset must idle high"

        await self.csr_write("SCRATCH_COLD_0", SCRATCH_COLD_0, COLD_PAT)
        await self.csr_write("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, WARM_PAT)
        got_c = await self.csr_read("SCRATCH_COLD_0_PRE", SCRATCH_COLD_0, expected=COLD_PAT)
        got_w = await self.csr_read(
            "SCRATCH_COLD_WARM_0_PRE", SCRATCH_COLD_WARM_0, expected=WARM_PAT
        )
        self.pre_ok = True
        cocotb.log.info(
            "CHK-RESET-UNIT-PRE: COLD=0x%x COLD_WARM=0x%x before SEP WDT pulse",
            got_c,
            got_w,
        )

        dut.tb_sep_wdt_reset_n.value = 0
        for _ in range(_WDT_PULSE):
            await RisingEdge(dut.clk_smc_i)
        dut.tb_sep_wdt_reset_n.value = 1

        got_w = await self._await_warm_cleared(dut, "POST")
        got_c = await self.csr_read("SCRATCH_COLD_0_POST", SCRATCH_COLD_0, expected=COLD_PAT)
        self.cold_ok = True
        self.warm_ok = True
        cocotb.log.info(
            "CHK-RESET-UNIT-WDT: COLD stayed 0x%x COLD_WARM cleared to 0x%x",
            got_c,
            got_w,
        )
        cocotb.log.info(
            "CHK-RESET-UNIT-BASIC: pre=%s cold=%s warm=%s",
            self.pre_ok,
            self.cold_ok,
            self.warm_ok,
        )
