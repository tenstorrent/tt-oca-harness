# SPDX-License-Identifier: Apache-2.0
"""SMC OSS P1 coverage-gap: OCA_I3C_WRAP 3/4/5 HCI_VERSION probe."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i3c_wrap_extended_test_seq import smc_i3c_wrap_extended_test_seq


@pyuvm.test()
class smc_i3c_wrap_extended_test(smc_base_test):
    """P1 coverage-gap depth: OCA_I3C_WRAP 3/4/5 HCI_VERSION probe."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_wrap_extended_test_seq("smc_i3c_wrap_extended_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I3C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap: OCA_I3C_WRAP 3/4/5 HCI_VERSION probe",
        )
