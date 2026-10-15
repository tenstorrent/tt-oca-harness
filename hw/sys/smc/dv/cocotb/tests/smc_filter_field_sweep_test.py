# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-filter 3-field sweep x 4 entries x 2 dirs."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_filter_field_sweep_test_seq import smc_filter_field_sweep_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_filter_field_sweep_test(smc_base_test):
    """Per-filter 3-field sweep x 4 entries x 2 dirs."""

    required_evidence = ("CHK-FILTER-FIELD-RESET-SWEEP",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_field_sweep_test_seq("smc_filter_field_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            # Directed stimulus floor: 3 fields x 4 entries x 2 directions = 24
            # SEP_IN AXI filter CSR accesses; a floor taken from `seq.accesses`
            # would shrink with a sequence that stopped issuing them.
            min_csr_accesses=24,
            csr_accesses=seq.accesses,
            proxy=False,
            details="per-filter 3-field sweep x 4 entries x 2 dirs",
        )
