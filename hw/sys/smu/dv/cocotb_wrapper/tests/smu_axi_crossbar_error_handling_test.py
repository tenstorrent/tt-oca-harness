# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_crossbar_error_handling_test — SMU_ALL_008 PWRGOOD-only.

DV-CARD:          SMU_ALL_008   ANCHOR: smu_axi_crossbar_error_handling_test
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_crossbar_error_handling_test_seq import (
    smu_axi_crossbar_error_handling_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_crossbar_error_handling_test(smu_base_test):
    """SMU_ALL_008: PWRGOOD leave-TLR only; FAB-IN / DECODE are out of scope."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_axi_crossbar_error_handling_test SMU_ALL_008 (PWRGOOD-only)"
        )
        seq = smu_axi_crossbar_error_handling_test_seq(self)
        await seq.run()
