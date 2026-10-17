# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag2axi_ratio_floor_test — SMC fabric JTAG2AXI series completion across TCK ratios."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_jtag2axi_ratio_floor_test_seq import smu_dtp_jtag2axi_ratio_floor_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag2axi_ratio_floor_test(smu_base_test):
    """Series write and single-load reads at TCK to clk_smu_i ratios 4.0, 4.8, 3.2, 2.0, 4.0."""

    use_shared_env = True
    # The TCK to clk_smu_i ratio is set per leg by the sequence, so the base test applies no floor.
    min_jtag_smu_ratio = None
    required_evidence = (
        "CHK-DBG-RATIO-COMPLETE-4P0",
        "CHK-DBG-RATIO-COMPLETE-4P8",
        "CHK-DBG-RATIO-OP3-RULE",
        "CHK-DBG-RATIO-RECOVERY",
        "CHK-DBG-RATIO-SETUP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_jtag2axi_ratio_floor_test SEP=1 JTAG")
        await smu_dtp_jtag2axi_ratio_floor_test_seq(self).run()
