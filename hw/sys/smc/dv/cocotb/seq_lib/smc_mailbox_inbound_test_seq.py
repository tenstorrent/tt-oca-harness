# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: inbound mailbox 0 CSR precheck (TC_SMC_P1CG_01).

The existing mailbox tests (P0/P1 P1-5) only touch outbound mailbox 0
at 0xC001_8000. RTL exposes 30 outbound + 30 inbound mailboxes; this
test covers the inbound-mailbox 0 STATUS/ERROR/IRQ CSR surface after
enabling the mailbox clock-gate.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = 0xC001_0018  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
MAILBOX_CG_EN = 1 << 1

MAILBOX0_INBOUND_STATUS      = 0xC001_8810
MAILBOX0_INBOUND_ERROR_FLAGS = 0xC001_8818
MAILBOX0_INBOUND_IRQEN       = 0xC001_8838


class smc_mailbox_inbound_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL,
                             cg | MAILBOX_CG_EN)
        # Inbound mailbox 0 surface — strict reads asserting reset content,
        # identical on Verilator and VCS. ERROR_FLAGS and IRQEN clear are RDL
        # reset constants (axil_mailbox.rdl) -> spec-anchored. STATUS=0x1 is a
        # REGRESSION-LOCK: the RDL reset of `empty` is 0x0, but the field is a
        # wire to the FIFO-empty flag, which reads 1 on an empty FIFO at reset --
        # so this locks observed HW behaviour, not a spec reset constant.
        await self.csr_read("MBOX0_INBOUND_STATUS",
                            MAILBOX0_INBOUND_STATUS, expected=0x1)
        await self.csr_read("MBOX0_INBOUND_ERROR_FLAGS",
                            MAILBOX0_INBOUND_ERROR_FLAGS, expected=0x0)
        await self.csr_read("MBOX0_INBOUND_IRQEN",
                            MAILBOX0_INBOUND_IRQEN, expected=0x0)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        assert self.accesses == 6, "mailbox inbound CSR sequence mismatch"
