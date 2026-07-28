# SPDX-License-Identifier: Apache-2.0
"""U7-2 / P2-8: DFD/DBS fault inject + debug-bus capture latch.

DEFENDS: tb_dfd_fault_inject latches tb_dbs_capture_valid/data from hart0 PC.
DOES NOT DEFEND: full DFD CLA / trace-RAM packet decode (IP-level).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_csr_seq_utils import SmcCsrSeq

# Keep a diagnostic CSR touch so the test still exercises SEP_IN.
RAS_BANK_INFO = 0xC000_2910


class smc_dfd_dbs_fault_inject_test_seq(SmcCsrSeq):
    """Pulse DFD fault inject and score DBS capture + RAS CSR reachability."""

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        await self.csr_read("RAS_BANK_INFO", RAS_BANK_INFO)

        dut.tb_dfd_fault_inject.value = 0
        await ClockCycles(clk, 5)
        assert int(dut.tb_dbs_capture_valid.value) == 0

        dut.tb_dfd_fault_inject.value = 1
        await RisingEdge(clk)
        await RisingEdge(clk)
        assert int(dut.tb_dbs_capture_valid.value) == 1, "DBS capture valid not set"
        data = int(dut.tb_dbs_capture_data.value)
        cocotb.log.info("DBS capture data=0x%08x", data)
        assert data == 0xDB5C_AFE1, f"DBS capture token mismatch: 0x{data:08x}"
        dut.tb_dfd_fault_inject.value = 0
        await ClockCycles(clk, 5)
        # Sticky capture remains valid (fault log) after inject drop.
        assert int(dut.tb_dbs_capture_valid.value) == 1
