# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Synchronized reset outputs assert asynchronously and release on the target clock.

Closes SMC-RST-SYNC.S1, SMC-RST-SYNC.S2, SMC-RST-SYNC.S3 and SMC-CLK-REF.S2
(clk_rst.adoc: Reset Synchronization and Timing Integrity, The Reference Clock
Domain): the cool reset pin is toggled at controlled phases and
``rst_primary_ref_clk_no`` / ``rst_primary_smc_clk_no`` are timestamped at
simulation-time resolution -- both assert in the same clk_ref_i-anchored
instant, each releases on a rising edge of its own clock, and more than one
target-clock edge separates the release anchor from each rise.
``rst_primary_periph_clk_no`` is unconnected in ``tb_top`` and is not claimed.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_reset_sync_edge_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_reset_sync_edge_test_seq import smc_reset_sync_edge_test_seq
from smc_base_test import smc_base_test

# Bounded reset WAIT_STATE handshakes the sequence dispatches (asserted, released).
EXPECTED_WAIT_CHECKS = 2


@pyuvm.test()
class smc_reset_sync_edge_test(smc_base_test):
    """Sub-cycle edge alignment of the synchronized primary resets."""

    required_evidence = (
        "CHK-RESET-SYNC-ASYNC-ASSERT",
        "CHK-RESET-SYNC-EDGE",
        "CHK-RESET-SYNC-MULTI-STAGE",
        "CHK-RESET-SYNC-REF-ANCHOR",
        "CHK-RESET-SYNC-SYNC-DEASSERT",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    async def run_scenario(self) -> None:
        seq = smc_reset_sync_edge_test_seq("reset_sync_edge_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= EXPECTED_WAIT_CHECKS, (
            f"scoreboard booked {sb.reset_wait_checks_seen} reset WAIT_STATE checks, expected at "
            f"least {EXPECTED_WAIT_CHECKS}"
        )
        assert None not in (seq.t_fall_ref, seq.t_rise_ref, seq.t_rise_smc, seq.stages_smc), (
            "the sequence ended without timestamping every reset edge it claims"
        )
        cocotb.log.info(
            "CHK-RESET-SYNC-EDGE: assert@%d ps release ref@%d ps smc@%d ps stages ref=%d smc=%d; "
            "scoreboard reset checks sample=%d wait=%d",
            seq.t_fall_ref,
            seq.t_rise_ref,
            seq.t_rise_smc,
            seq.stages_ref,
            seq.stages_smc,
            sb.reset_samples_seen,
            sb.reset_wait_checks_seen,
        )
