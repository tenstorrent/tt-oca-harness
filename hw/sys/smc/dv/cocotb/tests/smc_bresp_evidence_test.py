# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write responses of the SMC map's past-extent, gap and split-burst addresses over SEP_IN.

The merged response of a split two-beat write follows the rule memmap.adoc states (the last
beat's error code, else SLVERR after an earlier error, else OKAY); every declared past-extent
and gap write is recorded beside its declaration.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_bresp_evidence_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_bresp_evidence_test_seq import smc_bresp_evidence_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_bresp_evidence_test(smc_base_test):
    """Past-extent, hole and gap writes over SEP_IN; merged BRESP of split two-beat writes."""

    required_evidence = (
        "CHK-BURST-LIVE-UNCHANGED",
        "CHK-BURST-MERGE-RESP",
        "CHK-OBS-BRESP-TABLE",
        "CHK-OBS-BURST-TABLE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_bresp_evidence_test_seq("smc_bresp_evidence_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
