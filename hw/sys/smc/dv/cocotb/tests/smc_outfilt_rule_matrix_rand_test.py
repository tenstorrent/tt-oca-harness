# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded outbound filter rule tables: lowest matching entry decides, unmatched traffic passes."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outfilt_rule_matrix_rand_test_seq import smc_outfilt_rule_matrix_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_outfilt_rule_matrix_rand_test(smc_base_test):
    """Four drawn outbound rule tables, their JTAG probes graded against the table's golden."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-OFM-DENY-DECERR",
        "CHK-OFM-LOWEST-WINS",
        "CHK-OFM-MATCH-TERMS",
        "CHK-OFM-RESET",
        "CHK-OFM-RESTORE",
        "CHK-OFM-UNMATCHED-PASS",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outfilt_rule_matrix_rand_test_seq(
            "smc_outfilt_rule_matrix_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.total >= 44 and seq.jtag_accesses == seq.total, (
            f"{seq.jtag_accesses} JTAG probes, want the {seq.total} drawn and pinned"
        )
