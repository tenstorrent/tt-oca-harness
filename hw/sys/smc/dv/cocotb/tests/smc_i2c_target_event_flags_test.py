# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 TARGET_EVENTS start and stop flags: set only while the target is enabled."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_event_flags_test_seq import smc_i2c_target_event_flags_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_event_flags_test(smc_base_test):
    """A bench transfer with the target disabled and enabled, then the flag lifecycle."""

    required_evidence = (
        "CHK-I2C-TGT-FLAG-DISABLE-RETAIN-OBS",
        "CHK-I2C-TGT-FLAG-DISABLED-NOSET",
        "CHK-I2C-TGT-FLAG-SET",
        "CHK-I2C-TGT-FLAG-STICKY-W1C",
        "CHK-NONVAC",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_event_flags_test_seq("i2c_target_event_flags_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
