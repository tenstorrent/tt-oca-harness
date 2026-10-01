# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS mailbox 32 outbound + 32 inbound STATUS sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_mailbox_multi_instance_test_seq import smc_mailbox_multi_instance_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_multi_instance_test(smc_base_test):
    """Mailbox 32 outbound + 32 inbound STATUS sweep."""

    required_evidence = ("CHK-MAILBOX-CHANNEL-VECTOR",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_multi_instance_test_seq("smc_mailbox_multi_instance_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            # Directed stimulus floor: 32 outbound + 32 inbound mailbox STATUS
            # reads plus the 3 sweep prologue accesses. Literal here, not read
            # from `seq.accesses`.
            min_csr_accesses=67,
            csr_accesses=seq.accesses,
            proxy=False,
            details="mailbox 32 outbound + 32 inbound STATUS sweep",
        )
