# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO `interrupt_enable` as an output mask.

**Fails while the RTL uses `interrupt_enable` as the interrupt flop's clock
enable instead of an output mask** (see below).

SPEC (`hw/ip/gpio/doc/architecture.adoc:122`) defines the enable as a
combinational mask::

    interrupt_o = interrupt_enable && interrupt_trigger

RTL disagrees. `hw/ip/gpio/rtl/gpio.sv:253-261` uses `reg__interrupt_enable` as
the **clock enable** of the `interrupt` flop rather than as an output mask, and
`:302` is a bare ``assign interrupt_o = interrupt;`` with no AND. The
``always_comb`` at `:297-299` does compute ``nxt_interrupt = 1'b0`` when the
enable is low, but that value can never be captured because the same signal
gates the flop -- which is what shows the hold is not a deliberate latch: the
clear was written and the clock enable prevents it taking effect.

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
        self.chk_seen: set[str] = set()

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
        self.chk_seen.add("CHK-GPIO-IRQ-MASK-ARM")

        # ---- S5b: clear interrupt_enable ONLY; the pad stays high ----
        await self.csr_write("GPIO0_MASKED", GPIO0_DATA_CTRL, CFG_MASKED)
        await ClockCycles(dut.clk_smc_i, _SETTLE)
        got = self._irq(dut)
        assert got == 0, (
            f"CHK-GPIO-IRQ-MASK-DEASSERT: tb_gpio_irq_any stayed {got} after "
            f"DATA_CTRL 0x{CFG_ARMED:08x} -> 0x{CFG_MASKED:08x} (interrupt_enable "
            f"1->0, bit 18) with the pad still high and no other stimulus. SPEC "
            f"hw/ip/gpio/doc/architecture.adoc:122 requires "
            f"interrupt_o = interrupt_enable && interrupt_trigger; "
            f"gpio.sv:253-261 uses the enable as the interrupt "
            f"flop's clock enable and gpio.sv:302 drives interrupt_o from that "
            f"flop unqualified, so the cleared value at gpio.sv:297-299 can "
            f"never be captured"
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
        self.chk_seen.add("CHK-GPIO-IRQ-MASK-DEASSERT")

        # Restore: pad released and the wrap returned to its reset configuration,
        # so this sequence leaves no interrupt_enable programmed behind it.
        dut.tb_gpio_ext_drive_en.value = 0x0
        await self.csr_write("GPIO0_RESTORE", GPIO0_DATA_CTRL, 0)
        await self.csr_read("GPIO0_RESTORE_RB", GPIO0_DATA_CTRL, expected=0)

        self.assert_all_reachable(4, "GPIO_IRQ_MASK_DEASSERT")
