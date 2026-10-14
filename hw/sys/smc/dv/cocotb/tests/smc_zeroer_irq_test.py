# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer completion interrupt count, timing, INT_EN control and PLIC source 324.

Sources hw/sys/smc/doc/zeroer.adoc, hw/sys/smc/doc/interrupts.adoc, zeroer_ctrl.rdl.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_irq_test_seq import smc_zeroer_irq_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, independent of the sequence's own counter:
#   6 output-fabric pass-all filter writes                               6
#   DEST_ADDR and SIZE written and read back                             4
#   the idle STATUS read, the start writes and the STATUS polls         10
#   SIZE and DEST_ADDR cleared, SIZE read back                           3
ZEROER_IRQ_MIN_CSR_ACCESSES = 23


@pyuvm.test()
class smc_zeroer_irq_test(smc_base_test):
    """Count zeroer completion interrupt pulses for INT_EN set, clear, held and repeated jobs."""

    required_evidence = (
        "CHK-ZEROER-IRQ-ONE-PULSE",
        "CHK-ZEROER-IRQ-NONE-WHEN-DISABLED",
        "CHK-ZEROER-IRQ-AFTER-LAST-B",
        "CHK-ZEROER-IRQ-TWO-JOBS",
        "CHK-ZEROER-IRQ-ZERO-SIZE-WIDTH",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_irq_test_seq("smc_zeroer_irq_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_IRQ_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"{seq.jobs} zeroer job(s) observed on the completion interrupt",
        )
