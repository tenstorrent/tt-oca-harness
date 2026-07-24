# SPDX-License-Identifier: Apache-2.0
"""SMC OSS P1 coverage-gap: Cadence I3C AXIL extension probe."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_cdns_i3c_axil_test_seq import smc_cdns_i3c_axil_test_seq


@pyuvm.test()
class smc_cdns_i3c_axil_test(smc_base_test):
    """P1 coverage-gap depth: Cadence I3C AXIL extension probe."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cdns_i3c_axil_test_seq("smc_cdns_i3c_axil_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I3C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=True,
            details=(
                "CSR/DECERR window: Cadence I3C AXIL extension (U5 macro policy)"
            ),
        )
