# SPDX-License-Identifier: Apache-2.0
"""ECC/DFD/DBS bounded diagnostic VIP helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles


async def check_diagnostic_observability() -> None:
    """Check bounded fault/debug observability after diagnostic CSR probes."""
    dut = cocotb.top

    await ClockCycles(dut.clk_smc_i, 8)
    for signal in (
        dut.tb_sync_irq,
        dut.tb_axil_any_master_active,
        dut.rst_primary_smc_clk_no,
        dut.rst_wdt_smc_clk_no,
    ):
        assert signal.value.is_resolvable, f"{signal._name} is not resolvable"
    assert int(dut.tb_axil_any_master_active.value) == 0, (
        "Downstream AXI-Lite masters should be idle after diagnostic CSR probes"
    )
    cocotb.log.info(
        "Diagnostic bounded VIP observed sync_irq=%d axil_active=%d rst_primary=%d",
        int(dut.tb_sync_irq.value),
        int(dut.tb_axil_any_master_active.value),
        int(dut.rst_primary_smc_clk_no.value),
    )
