# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded response probes of every SMC component-map row, gap and outside-window class.

Spec sources: memmap.adoc Address Space Organization, the generated component map Past
Extent column, smc.rdl ocah_gap_resp.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_map_row_response_matrix_test_seq import smc_map_row_response_matrix_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_map_row_response_matrix_test(smc_base_test):
    """DECERR and 0xBADCAB1E at seeded past-extent, gap and outside points of the map."""

    required_evidence = (
        "CHK-MRR-GAP",
        "CHK-MRR-GATE-CLEAR",
        "CHK-MRR-OUTSIDE-WINDOWS",
        "CHK-MRR-PAST-EXTENT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_map_row_response_matrix_test_seq(
            "map_row_response_matrix_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.log_timeout_paths()
        seq.nonvac_fence()
