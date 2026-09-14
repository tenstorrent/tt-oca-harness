# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_otp_smc_map_rw_test — SMC OTP J2A MAP BIRA R/W (SEP=0, no Force)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_otp_smc_map_rw_test_seq import smu_dtp_otp_smc_map_rw_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_otp_smc_map_rw_test(smu_base_test):
    """OTP J2A MAP BIRA allow-path; gate tied open on SEP=0."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_dtp_otp_smc_map_rw_test TierC DTP-OTP-SMC-MAP-RW SEP=0 JTAG"
        )
        seq = smu_dtp_otp_smc_map_rw_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"otp_smc_map incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok} s4={seq.s4_ok}"
        )
