# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 event bits, SMBALERT and the target NACK count held to their write semantics."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_event_retain_test_seq import smc_i2c_event_retain_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_event_retain_test(smc_base_test):
    """Writes that must not clear I2C0 event fields, then the ones that must."""

    required_evidence = (
        "CHK-I2C-INTR-STATE-RETAIN",
        "CHK-I2C-NACK-COUNT-WRITE",
        "CHK-I2C-SMBALERT-HWCLR",
        "CHK-I2C-TARGET-EVENTS-CLEAR",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_event_retain_test_seq("i2c_event_retain_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
