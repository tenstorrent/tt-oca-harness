# SPDX-License-Identifier: Apache-2.0
"""U7-1 / P2-7: ECC SBE/DBE inject hooks on scratch bank0.

DEFENDS: inject_sbe/dbe + probe advances tb_cpu_ecc_inject_fire_count; clearing
inject stops further probe fires (recovery).
DOES NOT DEFEND: Rocket ECC syndrome CSR / precise RAS recovery FW policy.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_csr_seq_utils import SmcCsrSeq

RAS_BANK_INFO = 0xC000_2910


class smc_ecc_fault_inject_test_seq(SmcCsrSeq):
    """Score SBE then DBE inject fires via TB probe (no live CPU fetch needed)."""

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        await self.csr_read("RAS_BANK_INFO", RAS_BANK_INFO)

        dut.tb_cpu_ecc_inject_sbe.value = 0
        dut.tb_cpu_ecc_inject_dbe.value = 0
        dut.tb_cpu_ecc_inject_probe.value = 0
        await ClockCycles(clk, 2)
        base = int(dut.tb_cpu_ecc_inject_fire_count.value)

        # SBE + probe → fire
        dut.tb_cpu_ecc_inject_sbe.value = 1
        await RisingEdge(clk)
        dut.tb_cpu_ecc_inject_probe.value = 1
        await RisingEdge(clk)
        dut.tb_cpu_ecc_inject_probe.value = 0
        await RisingEdge(clk)
        sbe = int(dut.tb_cpu_ecc_inject_fire_count.value)
        cocotb.log.info("SBE fire_count %d -> %d", base, sbe)
        assert sbe == base + 1, f"SBE probe did not fire ({base} -> {sbe})"

        # Recovery: inject clear, probe must not increment
        dut.tb_cpu_ecc_inject_sbe.value = 0
        await RisingEdge(clk)
        dut.tb_cpu_ecc_inject_probe.value = 1
        await RisingEdge(clk)
        dut.tb_cpu_ecc_inject_probe.value = 0
        await RisingEdge(clk)
        mid = int(dut.tb_cpu_ecc_inject_fire_count.value)
        assert mid == sbe, f"probe without inject must not fire ({sbe} -> {mid})"

        # DBE + probe → fire
        dut.tb_cpu_ecc_inject_dbe.value = 1
        await RisingEdge(clk)
        dut.tb_cpu_ecc_inject_probe.value = 1
        await RisingEdge(clk)
        dut.tb_cpu_ecc_inject_probe.value = 0
        await RisingEdge(clk)
        dbe = int(dut.tb_cpu_ecc_inject_fire_count.value)
        cocotb.log.info("DBE fire_count %d -> %d", mid, dbe)
        assert dbe == mid + 1, f"DBE probe did not fire ({mid} -> {dbe})"

        dut.tb_cpu_ecc_inject_dbe.value = 0
        await ClockCycles(clk, 2)
