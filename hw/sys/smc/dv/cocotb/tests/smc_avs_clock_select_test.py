# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVS_CLOCK_SELECT source and bypass selection at the AVS clock pad.

Sources: hw/ip/avsbus_controller/doc/interface.adoc, avsbus_controller.rdl, smc-programming.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avs_clock_select_test_seq import smc_avs_clock_select_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avs_clock_select_test(smc_base_test):
    """Each AVS_CLOCK_SELECT setting and transition must reach the AVS clock pad."""

    required_evidence = (
        "CHK-AVS-SELECT-TABLE",
        "CHK-AVS-SELECT-TRANSITIONS",
        "CHK-AVS-SELECT-UNGATED-RECOVERY",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avs_clock_select_test_seq("avs_clock_select_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
