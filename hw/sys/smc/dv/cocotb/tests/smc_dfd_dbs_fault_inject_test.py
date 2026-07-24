# SPDX-License-Identifier: Apache-2.0
"""U7-2 / P2-8 DFD/DBS fault inject + capture."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_dfd_dbs_fault_inject_test_seq import (
    smc_dfd_dbs_fault_inject_test_seq,
)


@pyuvm.test()
class smc_dfd_dbs_fault_inject_test(smc_base_test):
    """Pulse tb_dfd_fault_inject and score tb_dbs_capture_*."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_dbs_fault_inject_test_seq("dfd_dbs_fault_inject_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="DFD fault inject latched DBS capture from hart0 PC",
        )
