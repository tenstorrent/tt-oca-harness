# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP TMP_STATUS register smoke test."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_tmp_status_register_smoke_test_seq import (
    dtp_jtag_tmp_status_register_smoke_test_seq,
)


@pyuvm.test()
class dtp_jtag_tmp_status_register_smoke_test(dtp_base_test):
    """Run the DTP VPLAN TMP_STATUS reset/read smoke scenario."""

    async def run_scenario(self) -> None:
        await self.start_seq(dtp_jtag_tmp_status_register_smoke_test_seq())
