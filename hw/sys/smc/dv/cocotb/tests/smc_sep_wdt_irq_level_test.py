# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP watchdog reset input inverted into raw tb_cpu_interrupts bit 282."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sep_wdt_irq_level_test_seq import smc_sep_wdt_irq_level_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sep_wdt_irq_level_test(smc_base_test):
    """Idle zero, first high after the pin falls, zero after pin release and warm reset release."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SEPWDT-ASSERT-HIGH",
        "CHK-SEPWDT-IDLE-ZERO",
        "CHK-SEPWDT-LATENCY-LOG",
        "CHK-SEPWDT-RELEASE-ZERO",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sep_wdt_irq_level_test_seq("sep_wdt_irq_level_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 4, f"phases {seq.phases}, want 4"
        assert seq.accesses >= 1, f"only {seq.accesses} SEP_IN accesses issued, want >= 1"
