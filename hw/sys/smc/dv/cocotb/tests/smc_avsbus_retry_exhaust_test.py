# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus retry path against a target that never answers."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_avsbus_retry_exhaust_test_seq import smc_avsbus_retry_exhaust_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_retry_exhaust_test(smc_base_test):
    """Exhaust the AVSBus retry budget on two unanswered commands."""

    required_evidence = (
        "CHK-AVS-RETRY-BUDGET-EXHAUSTED",
        "CHK-AVS-RETRY-FSM-PATH",
        "CHK-AVS-RETRY-IN-PROGRESS",
        "CHK-AVS-RETRY-INT-W1C",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_retry_exhaust_test_seq("smc_avsbus_retry_exhaust_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Directed stimulus floor: 2 AVS_CFG_0 writes and their readbacks,
            # 2 AVS_CMD writes, the entry AVS_INTERRUPT read, one poll pair,
            # the completion AVS_NORMAL_STATUS and AVS_INTERRUPT reads, and the
            # write-1-clear pair. Literal here, not read from `seq.accesses`.
            min_csr_accesses=13,
            csr_accesses=seq.accesses,
            proxy=False,
            details="AVSBus retry states and retry-budget interrupts at an unresponsive target",
        )
