# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_aperture_reset_state_test — SMC aperture CSR and clock-gate reset state."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_aperture_reset_state_test_seq import smu_smc_aperture_reset_state_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_aperture_reset_state_test(smu_base_test):
    """GLOBAL_BASE, LOCAL_BASE, REGION_SIZE, smc_region_size_o and CLOCK_GATE_CONTROL at reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_aperture_reset_state_test SEP=1 J2A")
        seq = smu_smc_aperture_reset_state_test_seq(self)
        await seq.run()
        assert seq.done, "aperture reset state scenario incomplete"
