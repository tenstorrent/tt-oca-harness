# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: abstractcs.busy and cmderr lifecycle through the DMI."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_abstractcs_lifecycle_test_seq import (
    PATTERN_C,
    smc_jtag_dm_abstractcs_lifecycle_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_abstractcs_lifecycle_test(smc_base_test):
    """A halted hart's program-buffer loop drives busy, and command misuse drives cmderr 1 and 2."""

    required_evidence = (
        "CHK-DM-BUSY-LIFECYCLE",
        "CHK-DM-BUSY-WRITE",
        "CHK-DM-CMDERR-AARSIZE",
        "CHK-DM-CMDERR-CMDTYPE",
        "CHK-DM-CMDERR-NOEXEC",
        "CHK-DM-CMDERR-NOTRANSFER",
        "CHK-DM-CMDERR-RECOVER-GPR32",
        "CHK-DM-CMDERR-REGNO",
        "CHK-DM-CMDERR-REPLACE",
        "CHK-DM-CMDERR-STORE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_abstractcs_lifecycle_test_seq("jtag_dm_abstractcs_lifecycle_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module abstractcs lifecycle scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: abstractcs busy and cmderr lifecycle on a halted hart",
            expected_bytes=PATTERN_C.to_bytes(4, "big"),
            observed_bytes=seq.x8_low.to_bytes(4, "big"),
        )
