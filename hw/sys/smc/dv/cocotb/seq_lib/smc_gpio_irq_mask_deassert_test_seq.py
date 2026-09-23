# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO `interrupt_enable` as an output mask.

`hw/ip/gpio/doc/architecture.adoc` defines the enable as a combinational
mask::

    interrupt_o = interrupt_enable && interrupt_trigger

`hw/ip/gpio/rtl/gpio.sv` implements it that way: the `interrupt` flop tracks
the trigger whether or not the enable is set, and `interrupt_o` is that flop
ANDed with `reg__interrupt_enable`, so clearing the enable releases the line
without disturbing the tracked trigger.

The sibling GPIO IRQ sequences hold `interrupt_enable` at 1 while the pad is
driven, so they prove the `interrupt_trigger` half of the spec formula only;
this sequence drives the mask half.

Structure. The check is two phases and the first is load-bearing:

* **S5a (arm).** Prove `interrupt_o == 0` with the pad low, then drive the pad
  high, require `interrupt_o == 1`, and **hold** it stable. Leave the pad high.
* **S5b (mask).** The *only* stimulus is the `interrupt_enable = 0` write; the
  pad is not touched. Require `interrupt_o` to fall and stay low.

Without S5a this proves nothing -- sampling a 0 that already held is satisfied
by a DUT with no interrupt logic at all.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)

# Field encoding per hw/ip/gpio/regs/gpio_intf.rdl.
_RX_ENABLE = 2 << 4  # enable_rx_tx = 2'b10, sample the pad
_IF_ENABLE = 1 << 16
_IRQ_ENABLE = 1 << 18
_TYPE_ACTIVE_HIGH = 0 << 20

# The two words differ in exactly one bit, so the stimulus in S5b is unambiguous.
CFG_ARMED = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | _TYPE_ACTIVE_HIGH
CFG_MASKED = _RX_ENABLE | _IF_ENABLE | _TYPE_ACTIVE_HIGH

_SETTLE = 24
_HOLD = 32


class smc_gpio_irq_mask_deassert_test_seq(SmcCsrSeq):
    """Clearing interrupt_enable must de-assert interrupt_o."""

    def __init__(self, name: str = "smc_gpio_irq_mask_deassert_test_seq") -> None:
        super().__init__(name)

    def _irq(self, dut) -> int:
        return int(dut.tb_gpio_irq_any.value)

    async def _drive(self, dut, value: int) -> None:
        dut.tb_gpio_ext_drive_value.value = value & 0x1
        await ClockCycles(dut.clk_smc_i, _SETTLE)

    async def _hold(self, dut, want: int, label: str) -> None:
        """Require the aggregate to sit at `want` for the whole window.

        A single sample cannot distinguish a stable level from a transient, and
        the S5b claim is specifically that the line *stays* down.
        """
        for cycle in range(_HOLD):
            got = self._irq(dut)
            assert got == want, (
                f"{label}: tb_gpio_irq_any left {want} after {cycle} of {_HOLD} "
                f"hold cycles (read {got})"
            )
            await ClockCycles(dut.clk_smc_i, 1)

    async def body(self) -> None:
        dut = cocotb.top

        dut.tb_gpio_ext_drive_en.value = 0x1
        dut.tb_gpio_ext_drive_value.value = 0x0

        # ---- S5a: arm interrupt_o = 1 and prove it is stable ----
        await self.csr_write("GPIO0_ARMED", GPIO0_DATA_CTRL, CFG_ARMED)
        await self._drive(dut, 0)
        assert dut.tb_gpio_irq_any.value.is_resolvable, "GPIO IRQ aggregate unresolvable"
        assert self._irq(dut) == 0, (
            "arm pre-check: tb_gpio_irq_any already 1 with the pad low and "
            "active-high level programmed -- the mask leg below could not then "
            "attribute a 0 to the enable write"
        )
        await self._drive(dut, 1)
        assert self._irq(dut) == 1, (
            "arm: pad high with interrupt_enable=1 and interrupt_type=active-high "
            "did not assert tb_gpio_irq_any"
        )
        await self._hold(dut, 1, "arm hold")
        cocotb.log.info(
            "CHK-GPIO-IRQ-MASK-ARM: DATA_CTRL=0x%08x (interrupt_enable=1), pad "
            "driven high, tb_gpio_irq_any=1 held stable for %d cycles. The pad "
            "is left high on purpose: the mask leg changes nothing but the "
            "enable bit",
            CFG_ARMED,
            _HOLD,
        )

        # ---- S5b: clear interrupt_enable ONLY; the pad stays high ----
        await self.csr_write("GPIO0_MASKED", GPIO0_DATA_CTRL, CFG_MASKED)
        await ClockCycles(dut.clk_smc_i, _SETTLE)
        got = self._irq(dut)
        assert got == 0, (
            f"CHK-GPIO-IRQ-MASK-DEASSERT: tb_gpio_irq_any stayed {got} after "
            f"DATA_CTRL 0x{CFG_ARMED:08x} -> 0x{CFG_MASKED:08x} (interrupt_enable "
            f"1->0, bit 18) with the pad still high and no other stimulus. "
            f"hw/ip/gpio/doc/architecture.adoc requires "
            f"interrupt_o = interrupt_enable && interrupt_trigger"
        )
        await self._hold(dut, 0, "mask hold")
        cocotb.log.info(
            "CHK-GPIO-IRQ-MASK-DEASSERT: DATA_CTRL 0x%08x -> 0x%08x "
            "(interrupt_enable 1->0, sole stimulus, pad held high) drove "
            "tb_gpio_irq_any 1 -> 0, held %d cycles. Armed by "
            "CHK-GPIO-IRQ-MASK-ARM, so the 0 is a transition and not a level "
            "that already held",
            CFG_ARMED,
            CFG_MASKED,
            _HOLD,
        )

        # Restore: pad released and the wrap returned to its reset configuration,
        # so this sequence leaves no interrupt_enable programmed behind it.
        dut.tb_gpio_ext_drive_en.value = 0x0
        await self.csr_write("GPIO0_RESTORE", GPIO0_DATA_CTRL, 0)
        await self.csr_read("GPIO0_RESTORE_RB", GPIO0_DATA_CTRL, expected=0)

        self.assert_all_reachable(4, "GPIO_IRQ_MASK_DEASSERT")
