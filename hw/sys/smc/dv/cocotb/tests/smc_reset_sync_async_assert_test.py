# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset output synchronizers assert asynchronously and release on their own clock edge.

Contract SMC_RESET_043, anchor smc_reset_sync_async_assert_test.
Allocated scenarios: RST-SYNC-OUT.S2, RST-SYNC-OUT.S3, RST-SYNC-OUT.S4, RST-SYNC-OUT.S6.
Spec sources: clk_rst.adoc (Reset Synchronization), port_table.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_sync_async_assert_test_seq import smc_reset_sync_async_assert_test_seq
from smc_base_test import smc_base_test

# Bounded WAIT_STATE handshakes the sequence dispatches (PG_RELEASED, FINAL_RELEASED).
EXPECTED_WAIT_CHECKS = 2


@pyuvm.test()
class smc_reset_sync_async_assert_test(smc_base_test):
    """Asynchronous assertion and own-edge release of every synchronized reset output."""

    required_evidence = (
        "CHK-REF-OUTPUTS-ASSERT-ASYNC",
        "CHK-PERIPH-OUTPUT-ASSERTS-ASYNC",
        "CHK-EACH-OUTPUT-RELEASES-ON-OWN-EDGE",
        "CHK-SOURCE-REASSERTS-IN-LATENCY",
        "CHK-NONVAC",
    )
    min_evidence = 5

    async def run_scenario(self) -> None:
        seq = smc_reset_sync_async_assert_test_seq("reset_sync_async_assert_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= EXPECTED_WAIT_CHECKS, (
            f"scoreboard booked {sb.reset_wait_checks_seen} reset WAIT_STATE checks, expected at "
            f"least {EXPECTED_WAIT_CHECKS}"
        )
        claimed = (
            seq.t_pin_low,
            seq.t_pg_high,
            seq.t_wdt_high,
            seq.t_final_release,
            seq.reassert_samples,
        )
        assert None not in claimed and len(seq.release_edges) == 6 and len(seq.final_edges) == 2, (
            "the sequence ended without timestamping every reset edge it claims"
        )
