# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_wdt_regs_test: CPU_CTRL WDT and TEST_CTRL scalar registers."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_wdt_regs_test_seq import smc_cpu_ctrl_wdt_regs_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_wdt_regs_test(smc_base_test):
    """Exercise the watchdog timeout and test-control scalar registers over SEP_IN."""

    required_evidence = (
        "CHK-WDT-RESET",
        "CHK-WDT-RW",
        "CHK-WDTRST-PULSE",
        "CHK-TESTCTRL-RO",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_wdt_regs_test_seq("cpu_ctrl_wdt_regs_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
