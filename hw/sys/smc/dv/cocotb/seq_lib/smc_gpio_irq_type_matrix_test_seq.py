# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO interrupt-type (polarity) matrix verification.

Programs GPIO wrap 0 for both level polarities and drives the pad externally to
prove the GPIO interrupt aggregate follows the configured polarity.

DATA_CTRL field encoding (hw/ip/gpio/regs/gpio_intf.rdl):
  * bit[5:4]   enable_rx_tx     2'b10 = RX enabled (sample pad)
  * bit16      interface_enable select register control of the pad
  * bit18      interrupt_enable
  * bit[21:20] interrupt_type   0 = active-high level, 1 = active-low level
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)

_RX_ENABLE = 2 << 4  # enable_rx_tx = 2'b10
_IF_ENABLE = 1 << 16
_IRQ_ENABLE = 1 << 18

_TYPE_ACTIVE_HIGH = 0 << 20
_TYPE_ACTIVE_LOW = 1 << 20

CFG_ACTIVE_HIGH = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | _TYPE_ACTIVE_HIGH
CFG_ACTIVE_LOW = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | _TYPE_ACTIVE_LOW

_SETTLE = 24


class smc_gpio_irq_type_matrix_test_seq(SmcCsrSeq):
    """Verify GPIO0 IRQ aggregate for active-high and active-low level types."""

    def __init__(self, name: str = "smc_gpio_irq_type_matrix_test_seq") -> None:
        super().__init__(name)

    def _irq(self, dut) -> int:
        return int(dut.tb_gpio_irq_any.value)

    async def _drive(self, dut, value: int) -> None:
        dut.tb_gpio_ext_drive_value.value = value & 0x1
        await ClockCycles(dut.clk_smc_i, _SETTLE)

    async def body(self) -> None:
        dut = cocotb.top

        dut.tb_gpio_ext_drive_en.value = 0x1
        dut.tb_gpio_ext_drive_value.value = 0x0

        # ---- Active-high level: IRQ asserts while the pad is high ----
        await self.csr_write("GPIO0_ACTIVE_HIGH", GPIO0_DATA_CTRL, CFG_ACTIVE_HIGH)
        await self._drive(dut, 0)
        assert dut.tb_gpio_irq_any.value.is_resolvable, "GPIO IRQ aggregate unresolvable"
        assert self._irq(dut) == 0, "active-high: IRQ set while pad low"
        await self._drive(dut, 1)
        assert self._irq(dut) == 1, "active-high: pad high did not assert IRQ"
        await self._drive(dut, 0)
        assert self._irq(dut) == 0, "active-high: IRQ did not clear when pad low"

        # ---- Active-low level: IRQ asserts while the pad is low ----
        await self.csr_write("GPIO0_ACTIVE_LOW", GPIO0_DATA_CTRL, CFG_ACTIVE_LOW)
        await self._drive(dut, 1)
        assert self._irq(dut) == 0, "active-low: IRQ set while pad high"
        await self._drive(dut, 0)
        assert self._irq(dut) == 1, "active-low: pad low did not assert IRQ"
        await self._drive(dut, 1)
        assert self._irq(dut) == 0, "active-low: IRQ did not clear when pad high"

        # Release the external pad drive.
        dut.tb_gpio_ext_drive_en.value = 0x0

        # `self.accesses` is incremented by every csr_* call in
        # smc_csr_seq_utils.py, so `self.accesses == <literal>` restates the
        # loop above and cannot fail on anything the DUT did
        # ([NO-ZERO-ACTIVITY-PASS]). `assert_all_reachable` cross-checks the
        # same count against the scoreboard, which a mis-bound analysis path
        # or a dead port fails.
        self.assert_all_reachable(2, "GPIO_IRQ_TYPE_MATRIX")
        cocotb.log.info("GPIO0 IRQ-type matrix verified (active-high + active-low level)")
