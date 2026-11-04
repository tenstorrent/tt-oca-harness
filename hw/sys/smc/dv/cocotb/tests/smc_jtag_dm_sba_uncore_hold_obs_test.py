# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: system bus access under and after an uncore reset hold, observed."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_sba_uncore_hold_obs_test_seq import (
    PATTERN_AFTER,
    smc_jtag_dm_sba_uncore_hold_obs_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_sba_uncore_hold_obs_test(smc_base_test):
    """A system bus write under the uncore reset hold leaves its CPU_CTRL.SCRATCH word unchanged
    and a write after the release lands; what the DMI shows under the hold is recorded."""

    required_evidence = (
        "CHK-DM-SBA-RESUMES-AFTER-RELEASE",
        "CHK-DM-SBA-WORD-UNCHANGED-UNDER-HOLD",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_sba_uncore_hold_obs_test_seq("jtag_dm_sba_uncore_hold_obs_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module system bus under uncore hold scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: system bus write under the uncore reset hold and after it",
            expected_bytes=PATTERN_AFTER.to_bytes(8, "big"),
            observed_bytes=seq.after_word.to_bytes(8, "big"),
        )
