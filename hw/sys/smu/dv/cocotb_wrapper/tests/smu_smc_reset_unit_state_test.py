# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_reset_unit_state_test — SMC reset-unit register state and idle outputs at boot."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_reset_unit_state_test_seq import smu_smc_reset_unit_state_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_reset_unit_state_test(smu_base_test):
    """Reset-unit CSR reset values and the idle isolate, skip-repair and sync outputs."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_reset_unit_state_test SEP=1 J2A")
        seq = smu_smc_reset_unit_state_test_seq(self)
        await seq.run()
        assert seq.done, "reset unit state scenario incomplete"
