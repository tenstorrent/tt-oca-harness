# SPDX-License-Identifier: Apache-2.0
"""GPIO external interrupt VIP helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles


async def check_gpio0_active_low_irq() -> None:
    """Drive GPIO0 externally and verify the GPIO interrupt aggregate."""
    dut = cocotb.top

    dut.tb_gpio_ext_drive_en.value = 0x1
    dut.tb_gpio_ext_drive_value.value = 0x1
    await ClockCycles(dut.clk_smc_i, 24)
    assert dut.tb_gpio_irq_any.value.is_resolvable, "GPIO IRQ aggregate is not resolvable"
    assert int(dut.tb_gpio_irq_any.value) == 0, "GPIO IRQ should start low with GPIO0 high"

    dut.tb_gpio_ext_drive_value.value = 0x0
    await ClockCycles(dut.clk_smc_i, 24)
    assert int(dut.tb_gpio_irq_any.value) == 1, "GPIO0 active-low drive did not assert IRQ"

    dut.tb_gpio_ext_drive_value.value = 0x1
    await ClockCycles(dut.clk_smc_i, 24)
    assert int(dut.tb_gpio_irq_any.value) == 0, "GPIO IRQ did not clear after GPIO0 release"

    dut.tb_gpio_ext_drive_en.value = 0x0
    cocotb.log.info("GPIO0 active-low IRQ VIP toggled external pad")
