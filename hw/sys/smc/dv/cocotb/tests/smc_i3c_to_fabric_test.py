# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM I3C-to-fabric test over real SYS AXI."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i3c_to_fabric_test_seq import smc_i3c_to_fabric_test_seq
from seq_lib.smc_i3c_vip_utils import check_i3c0_external_pull_low


@pyuvm.test()
class smc_i3c_to_fabric_test(smc_base_test):
    """Run the I3C CSR decode smoke through the SMC SYS AXI input."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_to_fabric_test_seq("i3c_to_fabric_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_i3c0_external_pull_low()
        await self.record_protocol_vip(
            SmcProtocolVipKind.I3C,
            type(self).__name__,
            csr_accesses=seq.reads + 2,
            proxy=True,
            details="I3C0 LSIO SCL/SDA external pull-low behavior checked",
        )
