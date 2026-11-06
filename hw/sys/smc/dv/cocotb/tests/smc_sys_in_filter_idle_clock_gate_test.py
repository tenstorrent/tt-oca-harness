# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The system inbound filter clock is gated while SYS_IN is idle and runs under traffic.

Spec source: fabric.adoc Fabric Topology.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sys_in_filter_idle_clock_gate_test_seq import (
    smc_sys_in_filter_idle_clock_gate_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sys_in_filter_idle_clock_gate_test(smc_base_test):
    """Idle window with the filter clock stopped, a SYS_IN read that wakes it, idle again."""

    required_evidence = (
        "CHK-SYS-IN-FILTER-CLK-IDLE-GATED",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sys_in_filter_idle_clock_gate_test_seq(
            "smc_sys_in_filter_idle_clock_gate_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.log_timeout_paths()
        seq.raise_fails()
