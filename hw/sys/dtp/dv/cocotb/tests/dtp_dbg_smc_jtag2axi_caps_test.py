# SPDX-License-Identifier: Apache-2.0
"""DTP SMC fabric JTAG2AXI_CAPS test."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_smc_jtag2axi_caps_test_seq import dtp_dbg_smc_jtag2axi_caps_test_seq


@pyuvm.test()
class dtp_dbg_smc_jtag2axi_caps_test(dtp_base_test):
    """Run the DTP VPLAN SMC fabric JTAG2AXI_CAPS scenario."""

    async def run_scenario(self) -> None:
        await self.start_seq(dtp_dbg_smc_jtag2axi_caps_test_seq())
