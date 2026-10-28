# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Record the write response of every declared past-extent and gap address of the SMC map.

The single-access responses are #3294's DECERR declarations; #3426 asks for the merged response
of a split write burst, and the leaf is held out of `all` until it is ruled.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_bresp_evidence_obs_test_seq import smc_bresp_evidence_obs_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_bresp_evidence_obs_test(smc_base_test):
    """Past-extent, hole and gap writes over SEP_IN with OBS lines; split-burst BRESP cases."""

    required_evidence = (
        "CHK-OBS-BRESP-TABLE",
        "CHK-OBS-BURST-TABLE",
        "CHK-BURST-LIVE-UNCHANGED",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_bresp_evidence_obs_test_seq("smc_bresp_evidence_obs_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
