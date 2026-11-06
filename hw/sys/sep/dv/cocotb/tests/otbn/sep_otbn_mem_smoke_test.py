# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN IMEM and DMEM take one 32-bit write and readback each while STATUS reads BUSY_SEC_WIPE_INT.

The leaf grades no DUT value of the memory accesses. The OTBN register text
states that while OTBN is busy a memory read returns 0, a write is ignored and
the access raises ILLEGAL_BUS_ACCESS; no SEP text states whether that holds
during the post-reset internal wipe, which lasts the whole no_cpu smoke. The
response codes, the readbacks and the SRAM request and write counters are
logged on one OBS-OTBN-MEM-BUSY-ACCESS record. CTRL-OTBN-MEM-PRECOND fails the
leaf unless STATUS reads BUSY_SEC_WIPE_INT before the accesses.
Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_otbn_mem_smoke_seq import (
    OTBN_DMEM_SMOKE_WORD,
    OTBN_IMEM_SMOKE_WORD,
    sep_otbn_mem_smoke_seq,
)


@pyuvm.test()
class sep_otbn_mem_smoke_test(sep_base_test):
    """Log the IMEM and DMEM write/readback results in the post-reset wipe state."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()
        seq = sep_otbn_mem_smoke_seq("otbn_mem_smoke_seq")
        await self.start_seq(seq)
        await ClockCycles(dut.clk_i, 20)

        counters = {
            mem: (
                self.rd(getattr(dut, f"otbn_{mem}_req_count_o")),
                self.rd(getattr(dut, f"otbn_{mem}_write_count_o")),
            )
            for mem in ("imem", "dmem")
        }
        fields = []
        for mem, (wr_resp, rd_resp, rdata), written in (
            ("imem", seq.imem, OTBN_IMEM_SMOKE_WORD),
            ("dmem", seq.dmem, OTBN_DMEM_SMOKE_WORD),
        ):
            reqs, writes = counters[mem]
            fields.append(
                f"{mem}_wr_resp={wr_resp} {mem}_rd_resp={rd_resp} "
                f"{mem}_written=0x{written:08x} {mem}_readback=0x{rdata:08x} "
                f"{mem}_reqs={reqs} {mem}_writes={writes}"
            )
        self.logger.info(
            "OBS-OTBN-MEM-BUSY-ACCESS status=0x%08x %s", seq.status_raw, " ".join(fields)
        )
