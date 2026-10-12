# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer busy status, completion and outstanding writes under a stalling SYS_OUT responder.

Contract SMC_POWER_DMA_ZEROER_023, anchor smc_zeroer_busy_outstanding_test.
Scenarios ZEROER-BUSY-COMPLETION.S1 to S5 and ZEROER-OUTSTANDING.S1 to S3.
Sources hw/sys/smc/doc/zeroer.adoc, hw/sys/smc/doc/fabric.adoc, hw/ip/zeroer/regs/zeroer_ctrl.rdl.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_busy_outstanding_test_seq import smc_zeroer_busy_outstanding_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, independent of the sequence's own counter:
#   6 output-fabric pass-all filter writes                                   6
#   DEST_ADDR, SIZE and start writes of the six jobs                        18
#   one STATUS read per job before, during or after the job, six jobs        6
ZEROER_BUSY_OUTSTANDING_MIN_CSR_ACCESSES = 30


@pyuvm.test()
class smc_zeroer_busy_outstanding_test(smc_base_test):
    """Zeroer STATUS, busy until the last B, stalls, holds, more than 32 bursts, AW and W order."""

    required_evidence = (
        "CHK-ZEROER-BUSY-LIFECYCLE",
        "CHK-ZEROER-BUSY-UNTIL-LAST-B",
        "CHK-ZEROER-RANDOM-STALL",
        "CHK-ZEROER-LONG-STALL",
        "CHK-ZEROER-NO-TIMEOUT-INDICATION",
        "CHK-ZEROER-GT32-BURSTS",
        "CHK-ZEROER-AW-CAP",
        "CHK-ZEROER-AW-W-ORDER",
        "CHK-NONVAC",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_busy_outstanding_test_seq("smc_zeroer_busy_outstanding_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_BUSY_OUTSTANDING_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="zeroer busy, outstanding and stall scenarios completed",
        )
