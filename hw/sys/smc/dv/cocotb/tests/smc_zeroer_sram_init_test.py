# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer SRAM initialisation, partial ranges, egress use, unmapped and denied targets, DMA.

Contract SMC_POWER_DMA_ZEROER_027, anchor smc_zeroer_sram_init_test.
Scenarios ZEROER-SRAM-INIT.S1 to .S4 and ACCEL-EGRESS-ATTRS.S7.
Sources doc/programmer/src/smc-programming.adoc, hw/sys/smc/doc/zeroer.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_zeroer_sram_init_test_seq import smc_zeroer_sram_init_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_zeroer_sram_init_test(smc_base_test):
    """Clear SRAM, partial ranges and an egress region; aim the zeroer and DMA at local targets."""

    required_evidence = (
        "CHK-ZEROER-SRAM-FULL",
        "CHK-ZEROER-SRAM-PARTIAL",
        "CHK-ZEROER-EGRESS-REGION",
        "CHK-ZEROER-UNMAPPED-OR-DENIED",
        "CHK-ACCEL-LOCAL-TARGETS",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_sram_init_test_seq("smc_zeroer_sram_init_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
