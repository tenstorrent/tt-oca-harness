# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DFX STATUS_SMU abort pins. Not DEBUG_CTRL reset reads."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfx_status_abort_test_seq import (
    EXPECTED_VALUE_CHECKS,
    smc_dfx_status_abort_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfx_status_abort_test(smc_base_test):
    """mem_repair_abort / mbist_abort → STATUS_SMU sticky bits."""

    required_evidence = (
        "CHK-DFX-ABORT-BASIC",
        "CHK-DFX-ABORT-IDLE",
        "CHK-DFX-ABORT-MBIST",
        "CHK-DFX-ABORT-REPAIR",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfx_status_abort_test_seq("dfx_status_abort_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The DUT-sensitive checks are in the sequence: each stage is an exact
        # STATUS_SMU equality reached inside a bounded poll loop that RAISES on
        # expiry, and the two sticky readbacks carry `expected=` so the
        # scoreboard compares them.
        #
        # `csr_read` does not compare `expected` itself, so whether those
        # compares reached the scoreboard is not determined upstream. The
        # sequence asserts that against `sys_axi_value_checks_seen`, and this
        # gate re-reads the scoreboard directly so the testcase-level verdict
        # rests on the analysis path having been bound, not on a value the
        # sequence copied out of it.
        sb = self.env.scoreboard
        assert sb.sys_axi_value_checks_seen >= EXPECTED_VALUE_CHECKS, (
            f"DFX abort: the scoreboard booked "
            f"{sb.sys_axi_value_checks_seen} value compare(s), expected at "
            f"least {EXPECTED_VALUE_CHECKS} for the two sticky readbacks "
            f"(observed STATUS_SMU words "
            f"{[hex(v) for v in seq.status_progression]})"
        )
