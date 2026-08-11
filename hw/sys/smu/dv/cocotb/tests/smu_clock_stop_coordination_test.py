# SPDX-License-Identifier: Apache-2.0
"""smu_clock_stop_coordination_test — SMU_ALL_006 boot-stall/IC-reset/clkstop.

DV-CARD:          SMU_ALL_006   ANCHOR: smu_clock_stop_coordination_test
DV-CARD-REVISION: 10   RECORD-SHA256: d4e8d5273983c0aa6cead03bdea268dedea1dae02876d88e207b74fcdc090c51
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md @ artifact_revision 10   ENV: cocotb

Card OWNS (narrowed Option B):
  DTP-BOOT-STALL.S1/S2, DTP-IC-RESET.S1/S3, DTP-CLKSTOP-AGG.S1/S2/S3
DTP-FEAT-GATE.* and INT-FEAT-CTRL-DTP-GATE are out of scope (re-homed to 008).
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

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_clock_stop_coordination_test SMU_ALL_006 under "
            "--dut smu SEP=0 (BOOT-STALL/IC-RESET/CLKSTOP-AGG only)"
        )
        seq = smu_clock_stop_coordination_test_seq(self)
        await seq.run()
