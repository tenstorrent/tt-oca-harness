# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_mailbox_threshold_lane_test - mailbox register behaviour.

Outbound mailbox 0 write-threshold interrupt: IRQS/STATUS latching with the enable clear, IRQP
gating, lane drop on enable clear, flush and acknowledge baseline, WIRQT clamp, and the observed
acknowledge while the occupancy still exceeds WIRQT.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_mailbox_threshold_lane_test_seq import (
    smu_smc_mailbox_threshold_lane_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_mailbox_threshold_lane_test(smu_base_test):
    """Mailbox 0 write-threshold interrupt lane."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_mailbox_threshold_lane_test")
        seq = smu_smc_mailbox_threshold_lane_test_seq(self)
        await seq.run()
