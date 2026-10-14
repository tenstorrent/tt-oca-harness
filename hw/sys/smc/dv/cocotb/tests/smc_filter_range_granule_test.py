# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter START_ADDR / END_ADDR granule write-back and read-only data_bus_width."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_filter_range_granule_test_seq import (
    ACCESS_COUNT,
    smc_filter_range_granule_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_filter_range_granule_test(smc_base_test):
    """Granule rounding and the read-only bus width on disabled filter entries."""

    required_evidence = (
        "CHK-DBW-READ-ONLY",
        "CHK-GRANULE-ALIGNED",
        "CHK-GRANULE-BANK-PARITY",
        "CHK-GRANULE-BURST0",
        "CHK-GRANULE-WRITEBACK-OBSERVE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_range_granule_test_seq("smc_filter_range_granule_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses == ACCESS_COUNT, f"{seq.accesses} SEP_IN accesses, want {ACCESS_COUNT}"
