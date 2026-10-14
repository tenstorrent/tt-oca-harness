# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU boot-time register read test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_boot_regs_read_test_seq import smc_cpu_boot_regs_read_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_boot_regs_read_test(smc_base_test):
    """Read the boot-time registers over SEP_IN and compare them with their reset values."""

    required_evidence = (
        "CHK-BOOT-APERTURE-RESET",
        "CHK-BOOT-CHIPCFG-RESET",
        "CHK-BOOT-DEBUG-RESET-N",
        "CHK-BOOT-DUMMY-BURST",
        "CHK-BOOT-DUMMY-WORDS",
        "CHK-BOOT-LOCALBASE-RO",
        "CHK-BOOT-RESET-VECTOR-RESET",
        "CHK-BOOT-SCRATCH-WIDTH",
        "CHK-BOOT-STRAP-WORD",
        "CHK-NONVAC",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_boot_regs_read_test_seq("cpu_boot_regs_read_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [c for c in self.required_evidence if c not in seq.chk_seen]
        assert not missing, f"missing CHK evidence: {missing} (seen={sorted(seq.chk_seen)})"
