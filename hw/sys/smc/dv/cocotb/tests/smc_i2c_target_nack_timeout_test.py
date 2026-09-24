# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C target stretch allowance running out, in both directions.

TARGET_TIMEOUT_CTRL limits how long the target may stretch within one
transaction. Past it the target NACKs an incoming byte or releases SDA for an
outgoing one; both are driven with nothing to release the hold.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_nack_timeout_test_seq import smc_i2c_target_nack_timeout_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_nack_timeout_test(smc_base_test):
    """A stretch nobody releases must end in the target's own NACK."""

    required_evidence = (
        "CHK-I2C-TGT-EVENTS-RETAIN",
        "CHK-I2C-TGT-NACK-TIMEOUT-RX",
        "CHK-I2C-TGT-NACK-TIMEOUT-TX",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_nack_timeout_test_seq("i2c_target_nack_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
