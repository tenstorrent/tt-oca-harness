# SPDX-License-Identifier: Apache-2.0
"""U7-1 / P2-7 ECC SBE/DBE inject on scratch bank0."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_ecc_fault_inject_test_seq import smc_ecc_fault_inject_test_seq


@pyuvm.test()
class smc_ecc_fault_inject_test(smc_base_test):
    """SBE inject fires during scratch FW boot; inject clear recovers."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ecc_fault_inject_test_seq("ecc_fault_inject_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="scratch bank0 SBE/DBE inject fire_count scored",
        )
