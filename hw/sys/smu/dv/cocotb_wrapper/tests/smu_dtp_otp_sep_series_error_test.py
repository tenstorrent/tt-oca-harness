# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_otp_sep_series_error_test — SEP OTP JTAG2AXIL series access and the in-span hole."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_otp_sep_series_error_test_seq import (
    smu_dtp_otp_sep_series_error_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_otp_sep_series_error_test(smu_base_test):
    """SEP OTP series NO_INCR and INCR reads, the SLVERR hole, sticky code, reset and isolation."""

    use_shared_env = True
    required_evidence = (
        "CHK-DBG-SEP-OTP-HOLE-SERIES",
        "CHK-DBG-SEP-OTP-HOLE-SINGLE",
        "CHK-DBG-SEP-OTP-ISOLATION",
        "CHK-DBG-SEP-OTP-POSCTRL",
        "CHK-DBG-SEP-OTP-RESET",
        "CHK-DBG-SEP-OTP-SETUP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_otp_sep_series_error_test SEP=1 JTAG")
        await smu_dtp_otp_sep_series_error_test_seq(self).run()
