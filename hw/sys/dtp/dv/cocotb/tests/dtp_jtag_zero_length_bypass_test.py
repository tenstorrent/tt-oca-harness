# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP ZERO_LENGTH_BYPASS instruction test."""

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_scan_ref_model import STAP_ORDER
from env.dtp_types import DTP_FEATURE_BYPASS, DTP_FEATURE_IR_DECODE
from seq_lib.dtp_jtag_zero_length_bypass_test_seq import dtp_jtag_zero_length_bypass_test_seq


@pyuvm.test()
class dtp_jtag_zero_length_bypass_test(dtp_base_test):
    """Run the DTP VPLAN zero-length bypass scenario."""

    required_features = (DTP_FEATURE_IR_DECODE, DTP_FEATURE_BYPASS)

    # The chain leg draws its STAP per pass, so every port carries a downstream TAP.
    stap_ds_attach = STAP_ORDER

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_zero_length_bypass_test_seq,
            "jtag_zero_length_bypass_seq",
            specific_knob="DTP_JTAG_ZERO_LENGTH_BYPASS_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_BASIC_JTAG_TEST_LOOPS",
        )
