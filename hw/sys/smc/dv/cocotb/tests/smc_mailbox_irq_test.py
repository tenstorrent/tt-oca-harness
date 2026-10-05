# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM mailbox IRQ-control test over real SYS AXI."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_mailbox_irq_test_seq import smc_mailbox_irq_test_seq
from seq_lib.smc_mailbox_vip_utils import check_mailbox_irq_source
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
# Composition (smc_mailbox_irq_test_seq, directed, no polling): 20 SEP_IN AXI
# accesses, every mailbox address an SMC_MAILBOX_OUTBOUND_MAILBOX_0_* symbol --
#   3  CLOCK_GATE_CONTROL: read, write (mailbox_cg_en set), read-back
#   2  MAILBOX_STATUS read + MAILBOX_ERROR_FLAGS read (exact idle expectations)
#   1  CPU_CTRL.SMC_ATTRIBUTES read, compared with the documented MailboxDepth
#      the WIRQT/RIRQT clamp expectation (min(written, MailboxDepth-1)) uses
#   6  WIRQT / RIRQT / IRQEN write + read-back pairs
#   6  the same three restored to 0, write + read-back pairs
#   2  CLOCK_GATE_CONTROL restore write + read-back
# The floor is a minimum, not the exact count: the sequence's own end gate
# asserts the exact 20 (`EXPECTED_ACCESSES`).
MAILBOX_IRQ_MIN_CSR_ACCESSES = 19


@pyuvm.test()
class smc_mailbox_irq_test(smc_base_test):
    """Run mailbox status and IRQ-control CSR checks."""

    required_evidence = (
        "CHK-MAILBOX-IRQ-ASSERT",
        "CHK-MAILBOX-IRQ-CLEAR",
        "CHK-MAILBOX-IRQ-IDLE",
        "CHK-MAILBOX-IRQ-SOURCE",
        "CHK-MAILBOX-IRQT-CLAMP",
        "CHK-MAILBOX-IRQT-IN-RANGE",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_irq_test_seq("mailbox_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_mailbox_irq_source(mask=0x1)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=MAILBOX_IRQ_MIN_CSR_ACCESSES,
            proxy=False,
            # Names the observable this scenario actually checked:
            # check_mailbox_irq_source reads only tb_mailbox_irq_any (tb_top.sv,
            # |u_dut.u_smc.peripheral_interrupts[7:0]); tb_sync_irq is a
            # different net that this test never samples, and the IRQ agent is
            # not started here.
            details=(
                "SEP mailbox interrupt injection raised tb_mailbox_irq_any "
                "(peripheral_interrupts[7:0]); tb_sync_irq not sampled here"
            ),
        )
