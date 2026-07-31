# SPDX-License-Identifier: Apache-2.0
"""smu_smc_smoke_test — SMU P0 clock + cold/primary reset (SMU_001).

DV-CARD:          SMU_001   ANCHOR: smu_smc_smoke_test
DV-CARD-REVISION: 1   RECORD-SHA256: 5b9361826d09c05ab4159b600ab13234ef2c2416ae35e8a8b3d717da2fc89c9f
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb

Implements the approved SMU_001 checkbox card on ``tb_top`` / ``smu_uvm_top``.
Prior SYS_IN DECERR smoke checks are outside this card's OWNS and are not
part of this contract.
"""

from __future__ import annotations

import cocotb
import pyuvm

from seq_lib.smu_smc_smoke_test_seq import smu_smc_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_smoke_test(smu_base_test):
    """SMU_001: clk_smu/clk_ref advance + cold/primary reset hold/release."""

    async def bring_up(self) -> None:
        # Card owns the preload/release sequence; do not auto-release in base.
        self.logger.info(
            "SMU_001 bring_up deferred to sequence (preload with rst_cold held)"
        )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=BARE smu_smc_smoke_test SMU_001 under --dut smu SEP=0")
        seq = smu_smc_smoke_test_seq(self)
        await seq.run()
