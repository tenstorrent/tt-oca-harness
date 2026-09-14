# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""L2 partial-write drain recovers from timeout-forced CPU isolation."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_isolate_flush_test_seq import smc_cpu_l2_write_wedge_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_l2_write_wedge_test(smc_base_test):
    """Flush a pending L2 write, absorb late W beats, and reopen the path."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_l2_write_wedge_test_seq("cpu_l2_write_wedge_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.contracts == {
            "forced_reset",
            "drained_while_blocked",
            "late_write_beats_absorbed",
            "l2_write_recovered",
            "cluster_reopened",
        }, f"incomplete L2 write recovery contracts: {sorted(seq.contracts)}"
