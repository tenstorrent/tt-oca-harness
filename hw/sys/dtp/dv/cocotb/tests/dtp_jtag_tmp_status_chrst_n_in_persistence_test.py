# SPDX-License-Identifier: Apache-2.0
"""DTP TMP_STATUS persistence across chip reset test."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq import (
    dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq,
)


@pyuvm.test()
class dtp_jtag_tmp_status_chrst_n_in_persistence_test(dtp_base_test):
    """Run the DTP VPLAN TMP persistence across chip reset scenario."""

    async def run_scenario(self) -> None:
        await self.start_seq(dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq())
