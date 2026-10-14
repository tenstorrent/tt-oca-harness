# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outstanding access groups at, above and across subordinates of the two crossbars.

Spec sources: fabric.adoc Configuration Parameters, scratch.rdl SCRATCH, chip_config.rdl.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_xbar_outstanding_limits_test_seq import smc_xbar_outstanding_limits_test_seq
from smc_base_test import smc_base_test

# Accesses the sequence issues: setup 36, groups 4, 5, 8, 12, 4+4, 8, 9, 16, 24, 16 plus
# 8 readbacks, teardown 16.
STIMULUS_FLOOR = 170


@pyuvm.test()
class smc_xbar_outstanding_limits_test(smc_base_test):
    """Outstanding read groups of 4 to 24 over the AXI-Lite and local AXI4 crossbars."""

    required_evidence = (
        "CHK-XLIM-LITE-N4",
        "CHK-XLIM-LITE-OVER",
        "CHK-XLIM-LITE-MULTI",
        "CHK-XLIM-LITE-TWO-MGR",
        "CHK-XLIM-LOCAL-N8",
        "CHK-XLIM-LOCAL-OVER",
        "CHK-XLIM-LOCAL-MULTI",
        "CHK-XLIM-LOCAL-MIXED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_xbar_outstanding_limits_test_seq("smc_xbar_outstanding_limits_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "XBAR_OUTSTANDING_LIMITS")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
