# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse command-path ownership under program_enable and a lock set on an in-flight program."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_command_path_test_seq import smc_efuse_command_path_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_command_path_test(smc_base_test):
    """A read under program_enable reaches no bank command; a late lock leaves a program alone."""

    required_evidence = (
        "CHK-EFUSE-LOCK-AFTER-ISSUE",
        "CHK-EFUSE-READ-UNDER-PROGRAM-ENABLE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_command_path_test_seq("smc_efuse_command_path_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
