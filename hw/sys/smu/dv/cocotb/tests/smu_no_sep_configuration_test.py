# SPDX-License-Identifier: Apache-2.0
"""smu_no_sep_configuration_test — SMU P0 SEP=0 composition (SMU_005 rev 3).

DV-CARD:          SMU_005   ANCHOR: smu_no_sep_configuration_test
DV-CARD-REVISION: 3   RECORD-SHA256: 8198628add94387a6c5471526c9e6cc0f6d1c09d8a88650a8f6f75cd8f9c9993
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_VPLAN_DETAIL.md @ artifact_revision 3   ENV: cocotb
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_no_sep_configuration_test_seq import smu_no_sep_configuration_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_no_sep_configuration_test(smu_base_test):
    """SMU_005 rev3: SEP=0 lc_state 0xf0 ONLY (direct SMC path deferred)."""

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=BARE smu_no_sep_configuration_test SMU_005 SEP=0")
        seq = smu_no_sep_configuration_test_seq(self)
        await seq.run()
