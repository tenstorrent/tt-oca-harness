# SPDX-License-Identifier: Apache-2.0
"""SEP OTBN memory smoke test."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_otbn_mem_smoke_seq import sep_otbn_mem_smoke_seq


@pyuvm.test()
class sep_otbn_mem_smoke_test(sep_base_test):
    """Load OTBN memories through the SEP CPU-LSU AXI frontdoor."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()
        seq = sep_otbn_mem_smoke_seq("otbn_mem_smoke_seq")
        await self.start_seq(seq)
        await ClockCycles(dut.clk_i, 20)

        imem_writes = self.rd(dut.otbn_imem_write_count_o)
        dmem_writes = self.rd(dut.otbn_dmem_write_count_o)
        self.logger.info(
            "OTBN memory counters: imem=%d/%d dmem=%d/%d",
            self.rd(dut.otbn_imem_req_count_o),
            imem_writes,
            self.rd(dut.otbn_dmem_req_count_o),
            dmem_writes,
        )
        assert imem_writes > 0, "OTBN IMEM responder saw no writes"
        assert dmem_writes > 0, "OTBN DMEM responder saw no writes"
