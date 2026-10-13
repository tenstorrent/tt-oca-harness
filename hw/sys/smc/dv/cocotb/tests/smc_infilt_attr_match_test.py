# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The inbound filter matches AxPROT[1] and the source ID of SYS_IN accesses."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_infilt_attr_match_test_seq import smc_infilt_attr_match_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_infilt_attr_match_test(smc_base_test):
    """Inbound entries match AxPROT[1] equality, fall through, and ignore group_id."""

    required_evidence = (
        "CHK-INB-NS0-EQUALITY",
        "CHK-INB-NS1-EQUALITY",
        "CHK-INB-NS-FALLTHROUGH",
        "CHK-INB-PROT-BITS-IGNORED",
        "CHK-INB-NS-PER-CHANNEL",
        "CHK-INB-SRCID-WILDCARD-ZERO",
        "CHK-INB-SRCID-NONZERO-VS-ZERO",
        "CHK-INB-GROUPID-INERT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_infilt_attr_match_test_seq("smc_infilt_attr_match_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        total = seq.accesses + seq.sys_accesses
        assert total >= 83, f"{total} accesses, fewer than the contract floor of 83"
