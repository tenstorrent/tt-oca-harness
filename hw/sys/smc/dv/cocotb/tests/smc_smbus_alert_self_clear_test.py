# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMBUS_CTRL.SMBALERT clears on an address match only, not on another address."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_smbus_alert_self_clear_test_seq import smc_smbus_alert_self_clear_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_alert_self_clear_test(smc_base_test):
    """Alert request kept by a transfer to 0x55 and cleared by one to the own address 0x10."""

    required_evidence = (
        "CHK-SELFCLEAR-OTHER-ADDR",
        "CHK-SELFCLEAR-RACE-LOG",
        "CHK-TIMEOUT-PATHS",
        "CHK-NONVAC",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_alert_self_clear_test_seq("smbus_alert_self_clear_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
