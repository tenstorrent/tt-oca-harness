# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_telemetry_queue_threshold_test - telemetry queue order, empty/full and buffer threshold."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_telemetry_queue_threshold_test_seq import smu_telemetry_queue_threshold_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_telemetry_queue_threshold_test(smu_base_test):
    """Eight ATB messages through receiver 0: pop order, STATUS and INTR_STATUS threshold."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_telemetry_queue_threshold_test SMU_MISC_PERIPH_012 SEP=1 J2A"
        )
        seq = smu_telemetry_queue_threshold_test_seq(self)
        await seq.run()
        assert seq.done, "telemetry queue threshold scenario incomplete"
