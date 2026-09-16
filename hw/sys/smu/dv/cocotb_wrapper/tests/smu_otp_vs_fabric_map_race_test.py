# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_otp_vs_fabric_map_race_test — OTP vs fabric MAP last-writer."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_otp_vs_fabric_map_race_test_seq import (
    smu_otp_vs_fabric_map_race_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_otp_vs_fabric_map_race_test(smu_base_test):
    """OTP vs fabric MAP race: coherent winner, no silent tear."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_otp_vs_fabric_map_race_test TierA OTP||fabric MAP race"
        )
        seq = smu_otp_vs_fabric_map_race_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok, (
            f"otp_vs_fabric race incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok}"
        )
