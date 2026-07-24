# SPDX-License-Identifier: Apache-2.0
"""SMC OSS P1 coverage-gap: SMC_EFUSE_MAP direct read."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_map_read_test_seq import smc_efuse_map_read_test_seq


@pyuvm.test()
class smc_efuse_map_read_test(smc_base_test):
    """P1 coverage-gap depth: SMC_EFUSE_MAP direct read."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_map_read_test_seq("smc_efuse_map_read_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap: SMC_EFUSE_MAP direct read",
        )
