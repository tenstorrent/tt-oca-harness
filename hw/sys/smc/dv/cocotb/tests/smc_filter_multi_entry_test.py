# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap round 2: filter 16 inbound + 16 outbound CONFIG sweep."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_filter_multi_entry_test_seq import smc_filter_multi_entry_test_seq


@pyuvm.test()
class smc_filter_multi_entry_test(smc_base_test):
    """P1 coverage-gap round 2: filter 16 inbound + 16 outbound CONFIG sweep."""

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
            # reset, per-slot signature readback, restore readback). Literal
            # here, not read from the sequence.
            min_csr_accesses=96,
            csr_accesses=seq.value_checks_measured,
            proxy=False,
            details=(
                "P1 coverage-gap round 2: 16 inbound + 16 outbound "
                "FILTER_CONFIG slots, each proved by a "
                "(direction,index)-unique signature read back at its own "
                "offset while all 32 signatures are co-resident (phased "
                "write-all/read-all, no per-slot restore in between); "
                f"scoreboard value compares={seq.value_checks_measured}"
            ),
        )
