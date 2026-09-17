# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two downstream AXI-Lite manager ports busy at the same time.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_axil_downstream_concurrency_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axil_downstream_concurrency_test_seq import (
    MIN_VALUE_CHECKS,
    smc_axil_downstream_concurrency_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axil_downstream_concurrency_test(smc_base_test):
    """Interleave eFuse-bank and external-window accesses in one outstanding group."""

    required_evidence = ("CHK-AXIL-DOWNSTREAM-CONCURRENCY",)
    min_evidence = 1

    async def run_scenario(self) -> None:
        seq = smc_axil_downstream_concurrency_test_seq("axil_downstream_concurrency_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the SCOREBOARD-measured value-compare tally, so the pass
        # cannot rest on the sequence counting its own loop.
        assert seq.value_checks is not None and seq.value_checks >= MIN_VALUE_CHECKS, (
            f"downstream concurrency run booked {seq.value_checks} scoreboard "
            f"value compare(s), expected at least {MIN_VALUE_CHECKS}"
        )
