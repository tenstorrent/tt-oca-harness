# SPDX-License-Identifier: Apache-2.0
"""SMC OSS eFuse-derived chip-config read test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_chip_config_read_test_seq import smc_efuse_chip_config_read_test_seq
from seq_lib.smc_efuse_vip_utils import check_efuse_otp_observability


@pyuvm.test()
class smc_efuse_chip_config_read_test(smc_base_test):
    """Run eFuse-derived chip-config read checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_chip_config_read_test_seq("efuse_chip_config_read_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_efuse_otp_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="eFuse-derived chip-config version/LC/RAS surface checked",
        )
