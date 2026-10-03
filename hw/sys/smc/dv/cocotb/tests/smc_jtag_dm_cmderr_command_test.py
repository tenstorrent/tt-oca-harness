# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: command writes while abstractcs.cmderr is nonzero."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_cmderr_command_test_seq import (
    CMDERR_HALT_RESUME,
    CMDERR_NONE,
    CMDERR_NOT_SUPPORTED,
    smc_jtag_dm_cmderr_command_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_cmderr_command_test(smc_base_test):
    """cmderr 4 -> 2 on a Quick Access write; stored command replaced; W1C clears."""

    required_evidence = (
        "CHK-JTAG-DM-CMDERR-CLEAR",
        "CHK-JTAG-DM-CMDERR-HALTRESUME",
        "CHK-JTAG-DM-CMDERR-OVERWRITE",
        "CHK-JTAG-DM-CMDERR-STORE",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_cmderr_command_test_seq("jtag_dm_cmderr_command_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module cmderr/command scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            # JTAG DMI only: the cmderr byte golden carries the fail-capability.
            min_csr_accesses=0,
            proxy=False,
            details=f"CPU JTAG DMI: cmderr trace {seq.cmderr_trace}",
            expected_bytes=bytes(
                [CMDERR_HALT_RESUME, CMDERR_NOT_SUPPORTED, CMDERR_NOT_SUPPORTED, CMDERR_NONE]
            ),
            observed_bytes=bytes(seq.cmderr_trace),
        )
