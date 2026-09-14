# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO and IRQ representative CSR precheck."""

from __future__ import annotations

import cocotb

from .smc_addr_map import gpio_intf_u32, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)

# DATA_CTRL field bits sourced by symbol from generated hw/ip/gpio/regs/gen/c/
# gpio_intf.h (same pattern as smc_gpio_p0_int_test_seq), never hand-shifted:
# a regenerated header must move these with it.
# Field encodings from hw/ip/gpio/regs/gen/adoc/gpio_intf.adoc (DATA_CTRL):
#   enable_rx_tx   2'b10 = RX enabled
#   interrupt_type 2'b01 = active-low level
_RX_ENABLE = 2 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_IRQ_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
_TYPE_ACTIVE_LOW = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bp")

GPIO_INPUT_ACTIVE_LOW_IRQ = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | _TYPE_ACTIVE_LOW

# Software-writable DATA_CTRL bits, by symbol. gpio_intf.adoc marks `pad2core`
# (bit 31) and `lsio_enable` (bit 25) `R` -- they present live pad/LSIO state,
# not what was written -- so the read-back is compared over this mask and the
# two RO bits are reported observed-only rather than folded into the golden.
DATA_CTRL_SW_MASK = (
    gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_SELECT_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_DISABLE_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bm")
)
DATA_CTRL_RO_MASK = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm") | gpio_intf_u32(
    "GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm"
)

MAILBOX_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
# axil_mailbox.rdl IRQEN (regwidth 64): eirq[2]/rtirq[1]/wtirq[0] all reset 0x0
# and no other field is declared, so the whole register reads 0 out of reset.
MAILBOX_IRQEN_RESET = 0x0

EXPECTED_ACCESSES = 3
# One scoreboard-side exact value compare (the IRQEN read). The DATA_CTRL
# read-back is compared here instead, because the scoreboard's `expected`
# path is a whole-word compare and this register has RO bits.
MIN_VALUE_CHECKS = 1


class smc_gpio_irq_active_test_seq(SmcCsrSeq):
    """Precheck IRQ-control decode; GPIO IRQ behavior is verified by the VIP helper."""

    def __init__(self, name: str = "smc_gpio_irq_active_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen

        await self.csr_write(
            "GPIO0_INPUT_ACTIVE_LOW_IRQ", GPIO0_DATA_CTRL, GPIO_INPUT_ACTIVE_LOW_IRQ
        )
        # Read-back proves the write landed in the DUT's register, not just that
        # the access completed: without it a write-only decode (or a dropped
        # write) is indistinguishable from a programmed IRQ configuration.
        readback = await self.csr_read("GPIO0_DATA_CTRL_READBACK", GPIO0_DATA_CTRL)
        got_sw = readback & DATA_CTRL_SW_MASK
        assert got_sw == GPIO_INPUT_ACTIVE_LOW_IRQ, (
            f"GPIO0 DATA_CTRL read back 0x{got_sw:08x} over the sw-writable mask "
            f"0x{DATA_CTRL_SW_MASK:08x}, expected 0x{GPIO_INPUT_ACTIVE_LOW_IRQ:08x}"
        )
        cocotb.log.info(
            "CHK-GPIO0-DATA-CTRL-READBACK: sw bits 0x%08x match the programmed "
            "RX + interface-enable + IRQ-enable + active-low-level word "
            "(RO bits 0x%08x observed 0x%08x, not checked evidence)",
            got_sw,
            DATA_CTRL_RO_MASK,
            readback & DATA_CTRL_RO_MASK,
        )

        await self.csr_read(
            "MAILBOX_IRQEN_AS_IRQ_PROXY", MAILBOX_IRQEN, expected=MAILBOX_IRQEN_RESET, length=8
        )
        cocotb.log.info(
            "CHK-MAILBOX-IRQEN-RESET: 0x%016x matches the axil_mailbox.rdl reset",
            MAILBOX_IRQEN_RESET,
        )

        self.assert_all_reachable(EXPECTED_ACCESSES, "GPIO/IRQ precheck")
        checked = sb.sys_axi_value_checks_seen - value_checks_before
        assert checked >= MIN_VALUE_CHECKS, (
            f"GPIO/IRQ precheck: the scoreboard performed {checked} exact value "
            f"compare(s), expected at least {MIN_VALUE_CHECKS} -- an access-only "
            f"sweep proves decode, not register content"
        )
