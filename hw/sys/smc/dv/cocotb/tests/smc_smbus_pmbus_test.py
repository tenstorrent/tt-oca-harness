# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM SMBus + PMBus protocol test (P2 Phase A #1)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_smbus_pmbus_test_seq import smc_smbus_pmbus_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_pmbus_test(smc_base_test):
    """P2-A / P2-11: SMBus ARA + PEC + PMBus Linear11 proof."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_pmbus_test_seq("smbus_pmbus_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=0,
            proxy=False,
            details=(
                "SMBus write-with-PEC + ARA query traversed tb_i2c0_* pins; "
                "PMBus Linear11 encode/decode round-trip verified"
            ),
        )
