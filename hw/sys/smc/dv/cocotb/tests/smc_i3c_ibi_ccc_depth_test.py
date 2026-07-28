# SPDX-License-Identifier: Apache-2.0
"""SMC OSS I3C IBI/CCC depth pin-level test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i3c_recovery_status_csr_test_seq import (
    smc_i3c_recovery_status_csr_test_seq,
)
from seq_lib.smc_i3c_vip_utils import check_i3c0_external_pull_low


@pyuvm.test()
class smc_i3c_ibi_ccc_depth_test(smc_base_test):
    """Run IBI/status CSR coverage plus LSIO pin checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_recovery_status_csr_test_seq("i3c_ibi_ccc_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_i3c0_external_pull_low()
        await self.record_protocol_vip(
            SmcProtocolVipKind.I3C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I3C0 LSIO SCL/SDA external pull-low behavior checked",
        )
