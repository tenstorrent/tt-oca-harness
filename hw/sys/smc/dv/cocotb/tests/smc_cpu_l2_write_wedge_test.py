# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""L2 write-response drain recovers from a timeout-forced CPU reset."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_isolate_flush_test_seq import smc_cpu_l2_write_wedge_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_l2_write_wedge_test(smc_base_test):
    """Flush a blocked B response and complete the reset handshake."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_l2_write_wedge_test_seq("cpu_l2_write_wedge_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.contracts == {
            "forced_reset",
            "drained_while_blocked",
            "blocked_master_isolated",
        }, f"incomplete L2 write recovery contracts: {sorted(seq.contracts)}"
