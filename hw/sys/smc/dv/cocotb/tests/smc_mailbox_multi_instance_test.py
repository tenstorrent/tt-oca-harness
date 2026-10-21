# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_006 ANCHOR: smc_mailbox_multi_instance_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 5b7e0bd4f31e30e2dc06963f7c2b0ee5c5dd0dbc7b0863a79f6d7fcfbc4c946c
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 7 ENV: cocotb
"""SMC OSS mailbox 32 outbound + 32 inbound STATUS sweep and access results."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_mailbox_multi_instance_test_seq import smc_mailbox_multi_instance_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_multi_instance_test(smc_base_test):
    """Mailbox 32 outbound + 32 inbound STATUS sweep and access results on all 64 apertures."""

    required_evidence = (
        "CHK-MAILBOX-CHANNEL-VECTOR",
        "CHK-MBX-EMPTY-B2B",
        "CHK-MBX-EMPTY-FLAGS",
        "CHK-MBX-EMPTY-READ",
        "CHK-MBX-ERRFLAGS-RC",
        "CHK-MBX-ERRFLAGS-RETAIN",
        "CHK-MBX-RO-WRITE-EFFECT",
        "CHK-MBX-RO-WRITE-FLAGS",
        "CHK-MBX-RO-WRITE-STATUS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_multi_instance_test_seq("smc_mailbox_multi_instance_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            # Directed stimulus floor: 32 outbound + 32 inbound mailbox STATUS
            # reads plus the 3 sweep prologue accesses; a floor taken from
            # `seq.accesses` would shrink with a sequence that stopped issuing
            # them.
            min_csr_accesses=67,
            csr_accesses=seq.accesses,
            proxy=False,
            details="mailbox 32 outbound + 32 inbound STATUS sweep",
        )
