# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-instance SMBUS_EN isolation of the SMBALERT gate across the three I2C instances."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_smbus_alert_instance_isolation_test_seq import (
    smc_smbus_alert_instance_isolation_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_alert_instance_isolation_test(smc_base_test):
    """Clearing one instance's SMBUS_EN leaves the other two instances' SMBALERT status at 1."""

    required_evidence = (
        "CHK-GATE-ALL-SEE-ALERT",
        "CHK-GATE-OTHERS-UNMASKED",
        "CHK-TIMEOUT-PATHS",
        "CHK-NONVAC",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_alert_instance_isolation_test_seq("smbus_alert_instance_isolation_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
