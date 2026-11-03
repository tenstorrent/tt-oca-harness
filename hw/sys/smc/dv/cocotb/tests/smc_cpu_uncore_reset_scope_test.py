# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A software uncore reset holds all four cores on its own edge and keeps isolate_req up until released.

Sources: cpu.adoc; the sentences are quoted in `seq_lib/smc_cpu_uncore_reset_scope_test_seq.py`.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_uncore_reset_scope_test_seq import smc_cpu_uncore_reset_scope_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_uncore_reset_scope_test(smc_base_test):
    """Per-edge record of the core and uncore resets around a held uncore reset."""

    required_evidence = (
        "CHK-ISOLATE-REQ-HELD-UNTIL-RELEASE",
        "CHK-UNCORE-HOLDS-ALL-CORES-SAME-EDGE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_uncore_reset_scope_test_seq("smc_cpu_uncore_reset_scope_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fall_edge is not None and seq.held_samples == 2000, (
            f"uncore fall edge {seq.fall_edge}, hold window {seq.held_samples} samples"
        )
