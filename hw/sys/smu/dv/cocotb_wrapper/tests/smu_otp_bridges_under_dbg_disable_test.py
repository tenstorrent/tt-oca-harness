# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_otp_bridges_under_dbg_disable_test - OTP bridges answer while the fabric one is shut."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_otp_bridges_under_dbg_disable_seq import SmuOtpBridgesUnderDbgDisableSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_otp_bridges_under_dbg_disable_test(smu_base_test):
    """SMC and SEP OTP JTAG2AXI complete under a posture that blocks the SMC fabric bridge."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_otp_bridges_under_dbg_disable_test SEP=1 "
            "PROD_END posture, both OTP bridges over the primary TAP"
        )
        seq = SmuOtpBridgesUnderDbgDisableSeq(self)
        await seq.run()
