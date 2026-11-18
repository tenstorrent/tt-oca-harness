# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster watchdog first-stage timeouts at PLIC source IDs 329 to 332."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_wdt_plic_source_ids_test_seq import smc_wdt_plic_source_ids_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_wdt_plic_source_ids_test(smc_base_test):
    """Arm each core's watchdog; its PLIC pending probe and the context 0 claim read 329 + core."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-WDT-PLIC-ID-329-332",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_wdt_plic_source_ids_test_seq("wdt_plic_source_ids_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
