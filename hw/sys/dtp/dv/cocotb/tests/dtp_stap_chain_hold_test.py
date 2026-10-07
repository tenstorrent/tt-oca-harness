# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_stap_chain_hold_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_stap_scan_test_seq import dtp_stap_scan_test_seq


@pyuvm.test()
class dtp_stap_chain_hold_test(dtp_base_test):
    """With the PTAP 3DCR select clear, IR and DR scans leave the STAP chain untouched."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_stap_scan_test_seq,
            "stap_chain_hold",
            scenario="stap_chain_hold",
            specific_knob="DTP_STAP_CHAIN_HOLD_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
