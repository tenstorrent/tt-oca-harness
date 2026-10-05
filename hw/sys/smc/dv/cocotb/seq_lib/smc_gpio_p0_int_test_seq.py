# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO wrap 0 rising/falling edge IRQ. Level types live in smc_gpio_irq_type_matrix_test."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)

_RX_ENABLE = 2 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_IRQ_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
_TYPE_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bp")
_TYPE_RISING = 2 << _TYPE_BP
_TYPE_FALLING = 3 << _TYPE_BP

CFG_RISING = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | _TYPE_RISING
CFG_FALLING = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | _TYPE_FALLING

_SETTLE = 24


class smc_gpio_p0_int_test_seq(SmcCsrSeq):
    """GPIO0 rising/falling edge IRQ vs pad edges."""

    def __init__(self, name: str = "smc_gpio_p0_int_test_seq") -> None:
        super().__init__(name)
        self.rising_ok = False
        self.falling_ok = False

    def _irq(self, dut) -> int:
        assert dut.tb_gpio_irq_any.value.is_resolvable, "GPIO IRQ aggregate unresolvable"
        return int(dut.tb_gpio_irq_any.value)

    async def _drive(self, dut, value: int) -> None:
        dut.tb_gpio_ext_drive_value.value = value & 0x1
        await ClockCycles(dut.clk_smc_i, _SETTLE)

    async def _await_irq_low(self, dut, label: str) -> None:
        clk = dut.clk_smc_i
        for _ in range(_SETTLE):
            await ClockCycles(clk, 1)
            if dut.tb_gpio_irq_any.value.is_resolvable and int(dut.tb_gpio_irq_any.value) == 0:
                return
        raise AssertionError(
            f"{label}: tb_gpio_irq_any stayed high last={dut.tb_gpio_irq_any.value}"
        )

    async def _await_irq_pulse(self, dut, label: str) -> None:
        """One-cycle registered pulse (gpio.sv), then deassert while pad held."""
        clk = dut.clk_smc_i
        for _ in range(_SETTLE):
            await ClockCycles(clk, 1)
            if dut.tb_gpio_irq_any.value.is_resolvable and int(dut.tb_gpio_irq_any.value) == 1:
                await self._await_irq_low(dut, f"{label}_deassert")
                return
        raise AssertionError(
            f"{label}: tb_gpio_irq_any never pulsed within {_SETTLE} cycles "
            f"last={dut.tb_gpio_irq_any.value}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        dut.tb_gpio_ext_drive_en.value = 0x1
        dut.tb_gpio_ext_drive_value.value = 0x0

        await self.csr_write("GPIO0_RISING", GPIO0_DATA_CTRL, CFG_RISING)
        await self._drive(dut, 0)
        assert self._irq(dut) == 0, "rising: IRQ set before rising edge"
        dut.tb_gpio_ext_drive_value.value = 0x1
        await self._await_irq_pulse(dut, "rising")
        self.rising_ok = True
        cocotb.log.info("CHK-GPIO-P0-INT-RISE: pad 0->1 pulsed tb_gpio_irq_any")

        await self.csr_write("GPIO0_FALLING", GPIO0_DATA_CTRL, CFG_FALLING)
        await self._drive(dut, 1)
        assert self._irq(dut) == 0, "falling: IRQ set before falling edge (pad held 1)"
        dut.tb_gpio_ext_drive_value.value = 0x0
        await self._await_irq_pulse(dut, "falling")
        self.falling_ok = True
        cocotb.log.info("CHK-GPIO-P0-INT-FALL: pad 1->0 pulsed tb_gpio_irq_any")

        dut.tb_gpio_ext_drive_en.value = 0x0
        await self.csr_write("GPIO0_RESTORE", GPIO0_DATA_CTRL, 0)
        cocotb.log.info(
            "CHK-GPIO-P0-INT-BASIC: rising=%s falling=%s",
            self.rising_ok,
            self.falling_ok,
        )
