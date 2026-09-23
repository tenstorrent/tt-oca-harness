# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN outstanding transactions against B and R ready-side backpressure.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_sep_in_axi_flow_control_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sep_in_axi_flow_control_test_seq import (
    MIN_VALUE_CHECKS,
    smc_sep_in_axi_flow_control_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sep_in_axi_flow_control_test(smc_base_test):
    """Pipeline SEP_IN accesses and hold the response channels back."""

    required_evidence = (
        "CHK-SEP-IN-FLOW-CONTROL",
        "CHK-SEP-IN-RESP-STABLE",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_sep_in_axi_flow_control_test_seq("sep_in_axi_flow_control_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the SCOREBOARD-measured value-compare tally, so the pass
        # cannot rest on the sequence counting its own loop.
        assert seq.value_checks is not None and seq.value_checks >= MIN_VALUE_CHECKS, (
            f"SEP_IN flow-control run booked {seq.value_checks} scoreboard value "
            f"compare(s), expected at least {MIN_VALUE_CHECKS}"
        )
