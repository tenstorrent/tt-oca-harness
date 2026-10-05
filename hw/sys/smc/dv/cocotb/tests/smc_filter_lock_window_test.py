# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Writes queued behind the write that locks a filter must be refused.

Locks filter 15 of the outbound and inbound banks and queues two
`FILTER_CONFIG` writes behind each locking write in one outstanding group.
`locked` is `woset`, so both writes must be refused and the register must
keep the locked reset word.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_filter_lock_window_test_seq import smc_filter_lock_window_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_filter_lock_window_test(smc_base_test):
    """Writes behind the locking write do not reach a locked filter."""

    required_evidence = ("CHK-FILTER-LOCK-WINDOW",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_lock_window_test_seq("smc_filter_lock_window_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.after is not None, "FILTER_CONFIG was not read back"
