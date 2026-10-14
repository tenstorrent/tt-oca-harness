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

    required_evidence = (
        "CHK-SMBUS-ALERT-SUS-ALERT",
        "CHK-SMBUS-ALERT-SUS-ARA",
        "CHK-SMBUS-ALERT-SUS-BASIC",
        "CHK-SMBUS-ALERT-SUS-CLR",
        "CHK-SMBUS-ALERT-SUS-SUSPEND",
    )
    min_evidence = 5

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
            # Straight-line accesses plus one mandatory read from each status
            # poll; anything above this bound is poll iterations that vary with
            # timing.
            #
            # The sequence raises when `_host_ara_read`'s result differs from
            # `_ARA_REPLY`, so the record carries no byte golden.
            min_csr_accesses=42,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"DUT-internal SMBALERT asserted, ARA answered 0x{seq.ara_reply:02X} "
                f"and hw-cleared it, then SMBSUS asserted and released"
            ),
        )
