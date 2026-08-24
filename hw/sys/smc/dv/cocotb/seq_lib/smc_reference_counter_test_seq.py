# SPDX-License-Identifier: Apache-2.0
"""CPU_CTRL REFERENCE_COUNTER is a refclk CDC counter, not the OCTS timer."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

REF_COUNT = smc_addr("SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR")
_REF_WAIT = 32


class smc_reference_counter_test_seq(SmcCsrSeq):
    """REFERENCE_COUNTER advances on clk_ref_i."""

    def __init__(self, name: str = "smc_reference_counter_test_seq") -> None:
        super().__init__(name)
        self.advance_ok = False

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        c0 = await self.csr_read("REF_COUNT_0", REF_COUNT, length=8)
        for _ in range(_REF_WAIT):
            await RisingEdge(dut.clk_ref_i)
        c1 = await self.csr_read("REF_COUNT_1", REF_COUNT, length=8)
        assert c1 > c0, (
            f"REFERENCE_COUNTER did not advance: 0x{c0:x} -> 0x{c1:x} "
            f"after {_REF_WAIT} ref clocks"
        )
        self.advance_ok = True
        cocotb.log.info(
            "CHK-REF-COUNT: 0x%x -> 0x%x after %d ref clocks",
            c0,
            c1,
            _REF_WAIT,
        )
        cocotb.log.info("CHK-REF-COUNT-BASIC: advance=%s", self.advance_ok)
