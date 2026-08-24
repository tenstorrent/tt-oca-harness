# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: inbound mailbox 0 STATUS/ERROR/IRQEN precheck."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_mailbox_inbound_test_seq import smc_mailbox_inbound_test_seq


@pyuvm.test()
class smc_mailbox_inbound_test(smc_base_test):
    """P1 coverage-gap depth: inbound mailbox 0 STATUS/ERROR/IRQEN precheck."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_inbound_test_seq("smc_mailbox_inbound_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap: inbound mailbox 0 STATUS/ERROR/IRQEN precheck",
        )
