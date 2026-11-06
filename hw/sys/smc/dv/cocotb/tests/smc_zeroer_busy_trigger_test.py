# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A CTRL_STATUS write while the zeroer is busy: ignored while issuing, accepted while draining.

Sources hw/sys/smc/doc/zeroer.adoc (the state-machine paragraph) and the CTRL_STATUS description
of hw/ip/zeroer/regs/zeroer_ctrl.rdl.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_busy_trigger_test_seq import smc_zeroer_busy_trigger_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   6 output-fabric pass-all filter writes                                   6
#   DEST_ADDR, SIZE and start writes of four jobs                           12
#   one STATUS read before, and one after each phase                         3
#   DEST_ADDR and SIZE readback of the issue window's second region           2
ZEROER_BUSY_TRIGGER_MIN_CSR_ACCESSES = 23


@pyuvm.test()
class smc_zeroer_busy_trigger_test(smc_base_test):
    """Second trigger in ST_ISSUE_* starts nothing; in ST_IDLE with outstanding B it starts at once."""

    required_evidence = (
        "CHK-ZEROER-BUSY-TRIGGER-DRAIN-STARTS",
        "CHK-ZEROER-BUSY-TRIGGER-ISSUE-IGNORED",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_busy_trigger_test_seq("smc_zeroer_busy_trigger_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_BUSY_TRIGGER_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="zeroer busy-trigger issue and drain windows graded",
        )
