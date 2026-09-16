# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_clock_stop_coordination_test — SMU_ALL_006 boot-stall/IC-reset/clkstop.

DV-CARD:          SMU_ALL_006   ANCHOR: smu_clock_stop_coordination_test

Card OWNS:
  DTP-BOOT-STALL.S1/S2, DTP-IC-RESET.S1/S3, DTP-CLKSTOP-AGG.S1/S2/S3
DTP-FEAT-GATE.* and INT-FEAT-CTRL-DTP-GATE are owned by SMU_ALL_008.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_clock_stop_coordination_test_seq import (
    smu_clock_stop_coordination_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_clock_stop_coordination_test(smu_base_test):
    """SMU_ALL_006: DTP boot-stall / IC-RESET / clock-stop aggregation."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_clock_stop_coordination_test SMU_ALL_006 under "
            "--dut smu (BOOT-STALL/IC-RESET/CLKSTOP-AGG only)"
        )
        seq = smu_clock_stop_coordination_test_seq(self)
        await seq.run()
