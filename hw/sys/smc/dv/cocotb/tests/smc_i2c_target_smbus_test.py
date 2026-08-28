# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target ARA and external SMBSUS# on pad40."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i2c_target_smbus_test_seq import smc_i2c_target_smbus_test_seq


@pyuvm.test()
class smc_i2c_target_smbus_test(smc_base_test):
    """VIP ARA + external SMBSUS# into DUT I2C0 SMBus target."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_smbus_test_seq("i2c_target_smbus_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert (
            seq.alert_asserted
            and seq.ara_ok
            and seq.alert_cleared
            and seq.suspend_ok
        ), (
            f"target_smbus incomplete alert={seq.alert_asserted} ara={seq.ara_ok} "
            f"clr={seq.alert_cleared} sus={seq.suspend_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Conservative stimulus floor: 36 accesses observed in the retained
            # regression runs; the ARA/SMBSUS status polls are a
            # timing-dependent remainder, so the floor is set below it. Literal
            # here, not read from `seq.accesses`.
            min_csr_accesses=28,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"VIP ARA + ext SMBSUS "
                f"ara_ok={seq.ara_ok} sus_ok={seq.suspend_ok}"
            ),
            expected_bytes=seq.expected_bytes,
            observed_bytes=seq.observed_bytes,
        )
