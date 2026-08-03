# SPDX-License-Identifier: Apache-2.0
"""smu_axi_crossbar_error_handling_test — SMU P0 ext_in DECERR (SMU_004).

DV-CARD:          SMU_004   ANCHOR: smu_axi_crossbar_error_handling_test
DV-CARD-REVISION: 1   RECORD-SHA256: 2e75f6f0bfff77a4d022bcc1009884d6e12f897405b372c48af9a1b4e01b986e
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_axi_crossbar_error_handling_test_seq import (
    smu_axi_crossbar_error_handling_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_crossbar_error_handling_test(smu_base_test):
    """SMU_004: unmatched ext_in DECERR (SEP=0 inbound filter isolate)."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_axi_crossbar_error_handling_test SMU_004 SEP=0"
        )
        seq = smu_axi_crossbar_error_handling_test_seq(self)
        await seq.run()
