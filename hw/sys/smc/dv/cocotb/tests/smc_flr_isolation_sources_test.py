# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Isolation request sources, the FLR latch and skip_mem_repair_o.

Sources: smc/doc/clk_rst.adoc (Function Level Reset and Isolation), smc/doc/cpu.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_flr_isolation_sources_test_seq import smc_flr_isolation_sources_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_flr_isolation_sources_test(smc_base_test):
    """Drive the three isolation sources and the FLR latch; sample the two outputs."""

    required_evidence = (
        "CHK-FLR-LATCH-CLEAR",
        "CHK-FLR-LATCH-SET",
        "CHK-FLR-PIN-SOURCE",
        "CHK-FLR-REG-SOURCE",
        "CHK-FLR-SOURCE-OR",
        "CHK-FLR-SW-NO-SKIP",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_flr_isolation_sources_test_seq("smc_flr_isolation_sources_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
