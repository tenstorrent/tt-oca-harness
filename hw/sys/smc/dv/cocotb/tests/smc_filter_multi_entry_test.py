# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter 16 inbound + 16 outbound CONFIG sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_filter_multi_entry_test_seq import smc_filter_multi_entry_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_filter_multi_entry_test(smc_base_test):
    """Filter 16 inbound + 16 outbound CONFIG sweep."""

    required_evidence = ("CHK-FILTER-MULTI-ENTRY-SLOT-IDENTITY",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_multi_entry_test_seq("smc_filter_multi_entry_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The observed side of the floor is the SCOREBOARD's own tally of
        # exact-value compares, not `seq.accesses`: a self-count compared
        # against a literal cannot detect a run in which the DUT traffic never
        # reached the checker.
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            # Directed stimulus floor: 32 slots x 3 value-checked reads (RDL
            # reset, per-slot signature readback, restore readback); a floor
            # derived from the sequence would shrink with a sequence that
            # stopped issuing them.
            min_csr_accesses=96,
            csr_accesses=seq.value_checks_measured,
            proxy=False,
            details=(
                "16 inbound + 16 outbound "
                "FILTER_CONFIG slots, each proved by a "
                "(direction,index)-unique signature read back at its own "
                "offset while all 32 signatures are co-resident (phased "
                "write-all/read-all, no per-slot restore in between); "
                f"scoreboard value compares={seq.value_checks_measured}"
            ),
        )
