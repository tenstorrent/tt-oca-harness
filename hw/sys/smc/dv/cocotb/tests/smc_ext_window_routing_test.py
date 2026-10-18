# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adopter window routing from the SEP_IN AXI port: eFuse SHIM range and external regions.

Spec sources: memmap.adoc AXI-Lite External Window, smc_external.rdl, smc.rdl smc_external.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_window_routing_test_seq import smc_ext_window_routing_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_window_routing_test(smc_base_test):
    """eFuse SHIM range, supplementary region, equal offsets, responses and window top."""

    required_evidence = (
        "CHK-EXT-REGIONS-IDENTICAL",
        "CHK-EXT-RESPONSE-RETURN",
        "CHK-EXT-SUPPLEMENTARY-ROUTED",
        "CHK-EXT-WINDOW-TOP",
        "CHK-NONVAC",
        "CHK-SHIM-BASE-ROUTED",
        "CHK-SHIM-LAST-WORD-ROUTED",
        "CHK-SHIM-PAST-RANGE-NOT-EFUSE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_window_routing_test_seq("ext_window_routing_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        booked = self.env.scoreboard.sys_axi_checks_seen
        assert booked >= seq.accesses, (
            f"scoreboard checked {booked} SEP_IN items for {seq.accesses} issued accesses"
        )
