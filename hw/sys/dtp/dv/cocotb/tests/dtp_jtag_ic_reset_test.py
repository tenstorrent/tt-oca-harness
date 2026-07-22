# SPDX-License-Identifier: Apache-2.0
"""DTP IC_RESET TDR test."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_ic_reset_test_seq import dtp_jtag_ic_reset_test_seq


@pyuvm.test()
class dtp_jtag_ic_reset_test(dtp_base_test):
    """Run the DTP VPLAN IC_RESET override and hold scenario."""

    async def run_scenario(self) -> None:
        await self.start_seq(dtp_jtag_ic_reset_test_seq())
