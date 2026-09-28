# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""L2 read drain recovers from a timeout-forced CPU reset."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_isolate_flush_test_seq import smc_cpu_l2_read_wedge_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_l2_read_wedge_test(smc_base_test):
    """Flush pending L2 reads while SEP_IN keeps R blocked."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-CPU-ISO-FLUSH-CLUSTER-REOPENED",
        "CHK-CPU-ISO-FLUSH-DRAINED-WHILE-BLOCKED",
        "CHK-CPU-ISO-FLUSH-FORCED-RESET",
        "CHK-CPU-ISO-FLUSH-L2-READ-RECOVERED",
        "CHK-CPU-ISO-FLUSH-STALE-R-DISCARDED",
    )
    min_evidence = 5

    async def run_scenario(self) -> None:
        seq = smc_cpu_l2_read_wedge_test_seq("cpu_l2_read_wedge_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.contracts == {
            "forced_reset",
            "drained_while_blocked",
            "stale_read_responses_discarded",
            "l2_read_recovered",
            "cluster_reopened",
        }, f"incomplete L2 read recovery contracts: {sorted(seq.contracts)}"
