# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMBALERT interrupt enable gating and routing to the peripheral interrupt vector."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_smbus_alert_irq_route_test_seq import smc_smbus_alert_irq_route_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_alert_irq_route_test(smc_base_test):
    """INTR_TEST.SMBALERT on each I2C instance, masked, routed, toggled and cleared."""

    required_evidence = (
        "CHK-IRQ-CLEAR",
        "CHK-IRQ-ENABLE-TOGGLE",
        "CHK-IRQ-LATENCY-LOG",
        "CHK-IRQ-MASKED",
        "CHK-IRQ-ROUTE",
        "CHK-IRQ-TEST-STATE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_alert_irq_route_test_seq("smbus_alert_irq_route_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
