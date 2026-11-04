# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The L2 frontend isolate holds four outstanding reads and, isolated, blocks a new one without terminating it.

Sources: cpu.adoc; the sentences are quoted in `seq_lib/smc_cpu_l2_isolate_depth_and_block_test_seq.py`.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_l2_isolate_depth_and_block_test_seq import (
    smc_cpu_l2_isolate_depth_and_block_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_l2_isolate_depth_and_block_test(smc_base_test):
    """Five held reads against the four-deep isolate, then a read into the isolated port."""

    required_evidence = (
        "CHK-L2-ISOLATE-DEPTH-FOUR",
        "CHK-L2-ISOLATED-BLOCKS-NEW-ACCESS",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_l2_isolate_depth_and_block_test_seq(
            "smc_cpu_l2_isolate_depth_and_block_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pending_trace and seq.blocked_samples == 512, (
            f"pending trace {len(seq.pending_trace)} samples, blocked window "
            f"{seq.blocked_samples} samples"
        )
