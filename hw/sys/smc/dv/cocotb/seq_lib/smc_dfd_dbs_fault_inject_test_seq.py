# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TB-glue demo (deferred): pulse tb_dfd_fault_inject → latch 0xDB5C_AFE1.

DOES NOT DEFEND: smc_dfd_wrap / hw/ip/dfd CLA / trace-RAM (real DFD RTL).
DEFENDS only: TB public capture ports wired in tb_top.sv.
"""

from __future__ import annotations

from .smc_addr_map import smc_addr
import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_csr_seq_utils import SmcCsrSeq

# Keep a diagnostic CSR touch so the test still exercises SEP_IN.
VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")


class smc_dfd_dbs_fault_inject_test_seq(SmcCsrSeq):
    """TB-glue: pulse inject pin and score hardcoded capture token."""

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        await self.csr_read("VERSION_LO", VERSION_LO)

        dut.tb_dfd_fault_inject.value = 0
        await ClockCycles(clk, 5)
        assert int(dut.tb_dbs_capture_valid.value) == 0

        dut.tb_dfd_fault_inject.value = 1
        await RisingEdge(clk)
        await RisingEdge(clk)
        assert int(dut.tb_dbs_capture_valid.value) == 1, "DBS capture valid not set"
        data = int(dut.tb_dbs_capture_data.value)
        cocotb.log.info("TB_GLUE DBS capture data=0x%08x (not DUT DFD)", data)
        assert data == 0xDB5C_AFE1, f"DBS capture token mismatch: 0x{data:08x}"
        dut.tb_dfd_fault_inject.value = 0
        await ClockCycles(clk, 5)
        # Sticky capture remains valid (fault log) after inject drop.
        assert int(dut.tb_dbs_capture_valid.value) == 1
