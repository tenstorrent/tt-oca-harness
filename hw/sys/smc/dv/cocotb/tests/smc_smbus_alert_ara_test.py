# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS SMBus SMBALERT# -> VIP ARA (DUT I2C0 target @ 0x10)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_smbus_alert_ara_test_seq import smc_smbus_alert_ara_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_alert_ara_test(smc_base_test):
    """U4-2: DUT SMBALERT# pad39 + VIP ARA @0x0C (TB CSR stands in for FW)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_alert_ara_test_seq("smbus_alert_ara_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.alert_asserted and seq.ara_ok and seq.alert_cleared, (
            "SMBALERT# ARA path failed: "
            f"assert={seq.alert_asserted} ara={seq.ara_ok} "
            f"clear={seq.alert_cleared}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the SMBALERT/ARA status polls are timing-dependent.
            min_csr_accesses=27,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "DUT I2C0 SMBALERT# pad39 -> VIP ARA@0x0C reply "
                f"0x{seq.observed_bytes.hex()} (target 0x10<<1); "
                "TB CSR stimulus (not Rocket FW)"
            ),
            expected_bytes=seq.expected_bytes,
            observed_bytes=seq.observed_bytes,
        )
