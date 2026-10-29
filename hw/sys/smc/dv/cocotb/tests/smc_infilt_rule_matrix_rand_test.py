# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded inbound filter rule tables: the lowest matching entry decides each SYS_IN probe."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_infilt_rule_matrix_rand_test_seq import smc_infilt_rule_matrix_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_infilt_rule_matrix_rand_test(smc_base_test):
    """Four drawn inbound rule tables, their SYS_IN probes graded against the table's golden."""

    required_evidence = (
        "CHK-IFM-LOWEST-WINS",
        "CHK-IFM-MATCH-TERMS",
        "CHK-IFM-NO-MATCH-BLOCK",
        "CHK-IFM-RESET",
        "CHK-IFM-RESTORE",
        "CHK-IFM-SRC-ID",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_infilt_rule_matrix_rand_test_seq(
            "smc_infilt_rule_matrix_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.probes == seq.total, f"{seq.probes} SYS_IN probes, want {seq.total}"
