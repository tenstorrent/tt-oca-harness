# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_otp_smc_series_error_test — OTP series NO_INCR + decode-hole SLVERR."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_otp_smc_series_error_test_seq import (
    smu_dtp_otp_smc_series_error_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_otp_smc_series_error_test(smu_base_test):
    """OTP J2A series NO_INCR + MAP-CTRL hole SLVERR; gate open on the SEP=1 wrapper."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_dtp_otp_smc_series_error_test "
            "TierC DTP-OTP-SMC-SERIES-ERROR SEP=1 JTAG"
        )
        seq = smu_dtp_otp_smc_series_error_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok, (
            f"otp_smc_series_error incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok}"
        )
