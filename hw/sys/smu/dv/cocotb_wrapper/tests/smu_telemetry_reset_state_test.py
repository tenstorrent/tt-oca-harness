# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_telemetry_reset_state_test — telemetry receiver register reset state."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_telemetry_reset_state_test_seq import smu_telemetry_reset_state_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_telemetry_reset_state_test(smu_base_test):
    """CTRL, STATUS, INTR_* and message registers of the three receivers at reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_telemetry_reset_state_test SEP=1 J2A")
        seq = smu_telemetry_reset_state_test_seq(self)
        await seq.run()
        assert seq.done, "telemetry reset state scenario incomplete"
