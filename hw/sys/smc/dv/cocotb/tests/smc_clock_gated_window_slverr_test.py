# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Clock-gated peripheral windows answer SLVERR with 0xBADCAB1E and recover."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clock_gated_window_slverr_test_seq import (
    MIN_SEP_IN_ACCESSES,
    smc_clock_gated_window_slverr_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_clock_gated_window_slverr_test(smc_base_test):
    """Each CLOCK_GATE_CONTROL peripheral enable turns its window into an SLVERR responder."""

    required_evidence = (
        "CHK-CG-ISOLATION",
        "CHK-CG-READ-SLVERR",
        "CHK-CG-RESTORED",
        "CHK-CG-TRANSITION-BOUNDED",
        "CHK-CG-WRITE-SLVERR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clock_gated_window_slverr_test_seq("clock_gated_window_slverr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.finished, "the sequence did not reach its restore step"
        assert seq.accesses >= MIN_SEP_IN_ACCESSES, (
            f"only {seq.accesses} SEP_IN accesses issued, want >= {MIN_SEP_IN_ACCESSES}"
        )
