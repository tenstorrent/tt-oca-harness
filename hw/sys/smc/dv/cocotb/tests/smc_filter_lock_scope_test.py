# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A filter lock refuses every write to the entry and freezes its decision."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_filter_lock_scope_test_seq import smc_filter_lock_scope_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_filter_lock_scope_test(smc_base_test):
    """Locked entries refuse FILTER_CONFIG, START_ADDR and END_ADDR writes, even queued ones."""

    required_evidence = (
        "CHK-LOCK-FROZEN-DENY",
        "CHK-LOCK-FROZEN-PERMIT",
        "CHK-LOCK-QUEUED-WRITES",
        "CHK-LOCK-READS-OKAY",
        "CHK-LOCK-WITH-FIELDS-OBSERVE",
        "CHK-LOCK-WRITES-REFUSED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_lock_scope_test_seq("smc_filter_lock_scope_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses + seq.jtag_accesses >= 79, "fewer accesses than the required floor"
