# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM AXI-Lite master idle test.

Samples the OR of all SMC AXI-Lite downstream master *_valid signals
(dtp_csr, pll, pvt, extension, efuse). With no CPU stimulus, the master
busses must stay idle after cold reset release.
"""

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_axil_idle_test_seq import smc_axil_idle_test_seq


@pyuvm.test()
class smc_axil_idle_test(smc_base_test):
    async def run_scenario(self) -> None:
        seq = smc_axil_idle_test_seq("axil_idle_seq")
        await self.start_seq(seq, self.env.axil_agent.sequencer)
