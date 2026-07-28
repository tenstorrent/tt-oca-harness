# SPDX-License-Identifier: Apache-2.0
"""eFuse/OTP bounded semantics helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles


async def check_efuse_otp_observability() -> None:
    """Check eFuse-bank observability used by OSS-safe OTP tests."""
    dut = cocotb.top

    await ClockCycles(dut.clk_smc_i, 8)
    assert dut.tb_axil_efuse_bank_active.value.is_resolvable, (
        "eFuse-bank AXI-Lite activity signal is not resolvable"
    )
    assert int(dut.tb_axil_efuse_bank_active.value) == 0, (
        "eFuse-bank AXI-Lite should be idle after bounded OTP checks"
    )
    cocotb.log.info("eFuse/OTP bounded semantics checker observed idle eFuse bank AXI-Lite")
