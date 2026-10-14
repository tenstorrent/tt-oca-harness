# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound filter entries match AxPROT[1], burst admission and a wildcard source ID.

Spec sources: axi_filter index.adoc (Match Then Permit), fabric.adoc, filter_ctrl.rdl FILTER_CONFIG.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outfilt_attr_match_test_seq import smc_outfilt_attr_match_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-OUT-NS0-EQUALITY",
    "CHK-OUT-NS1-EQUALITY",
    "CHK-OUT-NS-FALLTHROUGH",
    "CHK-OUT-PROT-BITS-IGNORED",
    "CHK-OUT-BURST0-SINGLE-ONLY",
    "CHK-OUT-BURST1-BOTH",
    "CHK-OUT-BURST-FALLTHROUGH",
    "CHK-OUT-SRCID-WILDCARD",
    "CHK-OUT-GROUPID-INERT",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_outfilt_attr_match_test(smc_base_test):
    """Deny entries match on AxPROT[1] and burst admission; src_id 0 and group_id never block."""

    required_evidence = REQUIRED
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outfilt_attr_match_test_seq("smc_outfilt_attr_match_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
