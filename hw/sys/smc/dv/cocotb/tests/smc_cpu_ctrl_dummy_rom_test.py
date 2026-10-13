# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_CPU_CTRL_015 / smc_cpu_ctrl_dummy_rom_test: DUMMY_ROM line and storage."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_dummy_rom_test_seq import smc_cpu_ctrl_dummy_rom_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_dummy_rom_test(smc_base_test):
    """Read the dummy boot-ROM line, overwrite each word with a pattern and restore it."""

    required_evidence = (
        "CHK-DROM-LINE",
        "CHK-DROM-RW",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_dummy_rom_test_seq("cpu_ctrl_dummy_rom_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
