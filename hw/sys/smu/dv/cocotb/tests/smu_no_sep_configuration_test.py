# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_no_sep_configuration_test — SMU P0 SEP=0 composition (SMU_005).

DV-CARD:          SMU_005   ANCHOR: smu_no_sep_configuration_test
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_no_sep_configuration_test_seq import smu_no_sep_configuration_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_no_sep_configuration_test(smu_base_test):
    """SMU_005: SEP=0 lc_state no-LCC word only; the direct SMN->SMC path is not covered."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=BARE smu_no_sep_configuration_test SMU_005 SEP=0")
        seq = smu_no_sep_configuration_test_seq(self)
        await seq.run()
