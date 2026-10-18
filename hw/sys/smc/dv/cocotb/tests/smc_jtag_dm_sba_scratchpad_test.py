# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: system bus access into the scratchpad memory through the DMI."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_sba_scratchpad_test_seq import smc_jtag_dm_sba_scratchpad_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_sba_scratchpad_test(smc_base_test):
    """System bus accesses of every width land in the scratchpad and match the AXI view."""

    required_evidence = (
        "CHK-DM-NOT-IMPL-DMI",
        "CHK-DM-SBA-64BIT",
        "CHK-DM-SBA-READ",
        "CHK-DM-SBA-VISIBLE",
        "CHK-DM-SBA-WIDTHS",
        "CHK-DM-SBA-WRITE",
        "CHK-DM-SBCS-CAPS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_sba_scratchpad_test_seq("jtag_dm_sba_scratchpad_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module system bus scratchpad scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: system bus 64-bit write and read of a scratchpad location",
            expected_bytes=seq.expected_word.to_bytes(8, "big"),
            observed_bytes=seq.observed_word.to_bytes(8, "big"),
        )
