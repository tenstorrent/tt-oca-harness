# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP TRST reset behavior test."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_types import DTP_FEATURE_IDCODE, DTP_FEATURE_IR_DECODE
from seq_lib.dtp_jtag_trst_test_seq import dtp_jtag_trst_test_seq


@pyuvm.test()
class dtp_jtag_trst_test(dtp_base_test):
    """TRST_N resets the TAP from every state before any TCK edge."""

    required_features = (DTP_FEATURE_IR_DECODE, DTP_FEATURE_IDCODE)

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_trst_test_seq,
            "jtag_trst_seq",
            specific_knob="DTP_JTAG_TRST_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_BASIC_JTAG_TEST_LOOPS",
        )
