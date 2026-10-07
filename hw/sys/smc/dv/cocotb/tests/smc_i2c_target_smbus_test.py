# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target ARA and external SMBSUS# on pad40."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_target_smbus_test_seq import smc_i2c_target_smbus_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_smbus_test(smc_base_test):
    """VIP ARA + external SMBSUS# into DUT I2C0 SMBus target."""

    required_evidence = (
        "CHK-I2C-TGT-SMBUS-ALERT",
        "CHK-I2C-TGT-SMBUS-ARA",
        "CHK-I2C-TGT-SMBUS-SUS-ASSERT",
        "CHK-I2C-TGT-SMBUS-SUS-CLR",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_smbus_test_seq("i2c_target_smbus_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Each of the four legs raises inside the sequence at the point it fails.
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the ARA/SMBSUS status polls are timing-dependent.
            min_csr_accesses=28,
            csr_accesses=seq.accesses,
            proxy=False,
            # The ARA reply is compared against _ARA_REPLY inside the sequence,
            # which raises on mismatch.
            details=(
                f"VIP ARA reply 0x{seq.observed_bytes.hex().upper()} accepted and "
                f"SMBALERT# hw-cleared; external SMBSUS# asserted and released"
            ),
        )
