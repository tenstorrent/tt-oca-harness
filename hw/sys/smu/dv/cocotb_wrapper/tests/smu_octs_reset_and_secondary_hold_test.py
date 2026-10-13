# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_octs_reset_and_secondary_hold_test — OCTS reset state and SECONDARY START hold."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_octs_reset_and_secondary_hold_test_seq import (
    smu_octs_reset_and_secondary_hold_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_octs_reset_and_secondary_hold_test(smu_base_test):
    """OCTS CSR and timer_count_o reset values, strap-low readback, SECONDARY START ignored."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_octs_reset_and_secondary_hold_test SMU_MISC_PERIPH_006 SEP=1 J2A"
        )
        seq = smu_octs_reset_and_secondary_hold_test_seq(self)
        await seq.run()
        assert seq.done, "OCTS reset and secondary hold scenario incomplete"
