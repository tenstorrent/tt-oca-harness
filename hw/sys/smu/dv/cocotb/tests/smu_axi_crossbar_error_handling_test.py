# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_crossbar_error_handling_test — SMU_ALL_008 Option-B PWRGOOD-only (r18).

DV-CARD:          SMU_ALL_008   ANCHOR: smu_axi_crossbar_error_handling_test
DV-CARD-REVISION: 18   RECORD-SHA256: 3be11166c37e13bc35de8dddbea105adf69f1f819525f7bb5bdcd292ffdf521d
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md @ artifact_revision 18   ENV: cocotb
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_axi_crossbar_error_handling_test_seq import (
    smu_axi_crossbar_error_handling_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_crossbar_error_handling_test(smu_base_test):
    """SMU_ALL_008 r18: PWRGOOD leave-TLR only (FAB/DECODE removed)."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_axi_crossbar_error_handling_test "
            "SMU_ALL_008 r18 SEP=0 (PWRGOOD-only)"
        )
        seq = smu_axi_crossbar_error_handling_test_seq(self)
        await seq.run()
