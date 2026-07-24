# SPDX-License-Identifier: Apache-2.0
"""Mailbox IRQ-source VIP helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles


async def check_mailbox_irq_source(mask: int = 0x1) -> None:
    """Inject SEP mailbox interrupts and verify the SMC sync IRQ output."""
    dut = cocotb.top

    dut.tb_sep_mailbox_interrupts.value = 0
    await ClockCycles(dut.clk_smc_i, 8)
    assert dut.tb_mailbox_irq_any.value.is_resolvable, "Mailbox IRQ aggregate is not resolvable"
    assert int(dut.tb_mailbox_irq_any.value) == 0, "Mailbox IRQ aggregate should start low"

    dut.tb_sep_mailbox_interrupts.value = mask
    await ClockCycles(dut.clk_smc_i, 8)
    assert int(dut.tb_mailbox_irq_any.value) == 1, (
        "Mailbox IRQ injection did not assert mailbox IRQ aggregate"
    )

    dut.tb_sep_mailbox_interrupts.value = 0
    await ClockCycles(dut.clk_smc_i, 8)
    assert int(dut.tb_mailbox_irq_any.value) == 0, (
        "Mailbox IRQ aggregate did not clear after mailbox IRQ release"
    )
    cocotb.log.info("Mailbox IRQ source VIP toggled mask=0x%02x", mask)
