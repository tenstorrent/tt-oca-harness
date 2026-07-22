# SPDX-License-Identifier: Apache-2.0
"""DTP JTAG_CAPS TDR test."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_jtag_caps_test_seq import dtp_dbg_jtag_caps_test_seq


@pyuvm.test()
class dtp_dbg_jtag_caps_test(dtp_base_test):
    """Run the DTP VPLAN JTAG_CAPS scenario."""

    async def run_scenario(self) -> None:
        await self.start_seq(dtp_dbg_jtag_caps_test_seq())
