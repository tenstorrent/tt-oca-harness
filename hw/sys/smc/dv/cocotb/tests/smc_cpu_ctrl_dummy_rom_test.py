# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_dummy_rom_test: DUMMY_ROM line, DUMMY_ROM_NULL and RESET_VECTOR storage."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_dummy_rom_test_seq import smc_cpu_ctrl_dummy_rom_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_dummy_rom_test(smc_base_test):
    """Check the dummy boot-ROM line, then walk RESET_VECTOR and DUMMY_ROM_NULL with the cores held."""

    required_evidence = (
        "CHK-CPU-CORES-HELD",
        "CHK-CPU-NULL-PATTERN",
        "CHK-CPU-NULL-RESET",
        "CHK-CPU-RESTORE",
        "CHK-CPU-RV-PATTERN",
        "CHK-CPU-RV-RESET",
        "CHK-DROM-LINE",
        "CHK-DROM-RW",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_dummy_rom_test_seq("cpu_ctrl_dummy_rom_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
