# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The log engine's shared THR port, four-word read-data FIFO and 512 KiB region clamp."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_log_engine_port_limits_test_seq import smc_log_engine_port_limits_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_log_engine_port_limits_test(smc_base_test):
    """Share THR with the CPU, stall the write side, and oversize the region on wrapper 0."""

    required_evidence = (
        "CHK-LE-THR-ARBITER-MERGE",
        "CHK-LOGENG-RDATA-FIFO-DEPTH-4",
        "CHK-LOGENG-REGION-CLAMP-512K",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_port_limits_test_seq("smc_log_engine_port_limits_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.merged) == 72, f"{len(seq.merged)} merged characters, 72 expected"
        assert seq.stalled_fetches == 4 and seq.total_fetches == 8, (
            f"{seq.stalled_fetches} fetches while stalled and {seq.total_fetches} in all"
        )
        assert seq.clamp_ar != 0, "the clamp leg recorded no fetch address"
