# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_scratch_bridge_readback_test — SCRATCH[0..15] write-readback over JTAG2AXI."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_scratch_bridge_readback_test_seq import (
    smu_smc_scratch_bridge_readback_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_scratch_bridge_readback_test(smu_base_test):
    """SCRATCH[n] reset value and write-readback through the SMC fabric JTAG2AXI bridge."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_smc_scratch_bridge_readback_test SMU_MISC_COMPOSITION_009 "
            "SEP=1 J2A"
        )
        seq = smu_smc_scratch_bridge_readback_test_seq(self)
        await seq.run()
        assert seq.done, "scratch bridge readback scenario incomplete"
