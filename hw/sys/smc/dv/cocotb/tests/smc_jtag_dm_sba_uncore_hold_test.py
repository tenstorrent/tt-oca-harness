# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: system bus access requested under an uncore reset hold is not started."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_sba_uncore_hold_test_seq import (
    PATTERN_AFTER,
    smc_jtag_dm_sba_uncore_hold_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_sba_uncore_hold_test(smc_base_test):
    """A system bus write requested under the uncore reset hold is not started: sbcs reads sbbusy 0
    and sberror 0, sbaddress0 does not advance, and the CPU_CTRL.SCRATCH word stays unchanged
    during and after the hold; a write after the release lands."""

    required_evidence = (
        "CHK-DM-SBA-NOT-STARTED-UNDER-HOLD",
        "CHK-DM-SBA-RESUMES-AFTER-RELEASE",
        "CHK-DM-SBA-WORD-UNCHANGED-UNDER-HOLD",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_sba_uncore_hold_test_seq("jtag_dm_sba_uncore_hold_seq")
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
