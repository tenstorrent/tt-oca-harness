# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DEBUG_CTRL register storage."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfx_debug_ctrl_storage_test_seq import smc_dfx_debug_ctrl_storage_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfx_debug_ctrl_storage_test(smc_base_test):
    """Write and read back every DEBUG_CTRL field over SEP_IN."""

    required_evidence = (
        "CHK-DFX-CTRL-B2B",
        "CHK-DFX-CTRL-BIT31",
        "CHK-DFX-CTRL-CLK-BITS",
        "CHK-DFX-CTRL-FIELDS",
        "CHK-DFX-CTRL-WALK1",
        "CHK-DFX-CTRL-XTRIG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfx_debug_ctrl_storage_test_seq("dfx_debug_ctrl_storage_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
