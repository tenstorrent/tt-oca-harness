# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_in_random_id_stress_test — seeded random-ID stream into the SMC SPM."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_in_random_id_stress_test_seq import smu_axi_in_random_id_stress_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_in_random_id_stress_test(smu_base_test):
    """Random IDs, sizes and lengths on ext_in against the SPM beside eight JTAG2AXI writes."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_axi_in_random_id_stress_test TierA ext_in random-ID SEP=1 "
            "J2A+ext_in+smu_axi_out"
        )
        await smu_axi_in_random_id_stress_test_seq(self).run()
