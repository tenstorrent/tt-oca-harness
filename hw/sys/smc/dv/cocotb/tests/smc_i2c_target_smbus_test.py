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

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_smbus_test_seq("i2c_target_smbus_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # No rollup assert here. Each of the four legs raises in the sequence at
        # the point it fails, so a flag can only be read True; restating them
        # would add a line that cannot print False.
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
            # No expected_bytes/observed_bytes: the ARA reply is compared
            # against _ARA_REPLY in the sequence and raises there, so a golden
            # on the record would report a compare whose operands were already
            # forced equal upstream.
            details=(
                f"VIP ARA reply 0x{seq.observed_bytes.hex().upper()} accepted and "
                f"SMBALERT# hw-cleared; external SMBSUS# asserted and released"
            ),
        )
