# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OTBN memory smoke test."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_otbn_mem_smoke_seq import sep_otbn_mem_smoke_seq

# One 32-bit write + one 32-bit readback per memory, as issued by
# sep_otbn_mem_smoke_seq.body().
EXP_IMEM_REQS, EXP_IMEM_WRITES = 2, 1
EXP_DMEM_REQS, EXP_DMEM_WRITES = 2, 1


@pyuvm.test()
class sep_otbn_mem_smoke_test(sep_base_test):
    """Load OTBN memories through the SEP CPU-LSU AXI frontdoor."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()
        seq = sep_otbn_mem_smoke_seq("otbn_mem_smoke_seq")
        await self.start_seq(seq)
        await ClockCycles(dut.clk_i, 20)

        imem_reqs = self.rd(dut.otbn_imem_req_count_o)
        imem_writes = self.rd(dut.otbn_imem_write_count_o)
        dmem_reqs = self.rd(dut.otbn_dmem_req_count_o)
        dmem_writes = self.rd(dut.otbn_dmem_write_count_o)
        self.logger.info(
            "OTBN memory counters: imem=%d/%d dmem=%d/%d",
            imem_reqs,
            imem_writes,
            dmem_reqs,
            dmem_writes,
        )
        # Exact counts, derived from the stimulus the sequence issues: one 32-bit
        # write plus one 32-bit readback per memory => 2 SRAM requests of which 1
        # is a write. Asserting `> 0` instead would pass on any access pattern,
        # including the 64-bit beat that splits one access into extra word
        # requests and is rejected by these SECDED memories. The STATUS poll in
        # the sequence targets the OTBN register map, not IMEM/DMEM, so it does
        # not contribute to these counters.
        assert (imem_reqs, imem_writes) == (EXP_IMEM_REQS, EXP_IMEM_WRITES), (
            f"OTBN IMEM SRAM requests {imem_reqs}/{imem_writes} != "
            f"expected {EXP_IMEM_REQS}/{EXP_IMEM_WRITES} (req/write)"
        )
        assert (dmem_reqs, dmem_writes) == (EXP_DMEM_REQS, EXP_DMEM_WRITES), (
            f"OTBN DMEM SRAM requests {dmem_reqs}/{dmem_writes} != "
            f"expected {EXP_DMEM_REQS}/{EXP_DMEM_WRITES} (req/write)"
        )
