# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_otp_smc_complete_rw_test — OTP MAP SPARE walk (SEP=1)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_otp_smc_complete_rw_test_seq import (
    smu_dtp_otp_smc_complete_rw_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_otp_smc_complete_rw_test(smu_base_test):
    """OTP+fabric+shadow MAP SPARE walk; gated-deny is not claimed."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_dtp_otp_smc_complete_rw_test TierC DTP-OTP-SMC-COMPLETE-RW SEP=1 JTAG"
        )
        seq = smu_dtp_otp_smc_complete_rw_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"otp_smc_complete incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok}"
        )
