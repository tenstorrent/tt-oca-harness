# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DUT-internal SMBALERT, ARA, and SMBSUS."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_smbus_alert_suspend_test_seq import (
    smc_smbus_alert_suspend_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_alert_suspend_test(smc_base_test):
    """I2C0 target SMBALERT + I2C1 ARA/IRQ + SMBSUS sideband."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_alert_suspend_test_seq("smbus_alert_suspend_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.alert_seen and seq.ara_ok and seq.alert_cleared and seq.suspend_ok, (
            f"alert_suspend incomplete alert={seq.alert_seen} ara={seq.ara_ok} "
            f"clr={seq.alert_cleared} sus={seq.suspend_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"DUT-internal SMBALERT/ARA/SMBSUS ara_ok={seq.ara_ok} sus_ok={seq.suspend_ok}"
            ),
        )
