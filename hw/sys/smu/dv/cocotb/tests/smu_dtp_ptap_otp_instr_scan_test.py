# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_ptap_otp_instr_scan_test — PTAP OTP CAPS + SINGLE_OP IR/DR (SEP=0)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_ptap_otp_instr_scan_test_seq import (
    smu_dtp_ptap_otp_instr_scan_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_ptap_otp_instr_scan_test(smu_base_test):
    """OTP CAPS + SMC TDR echo + SEP SINGLE_OP BYPASS; no MAP R/W."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_dtp_ptap_otp_instr_scan_test TierC PTAP-OTP-INSTR-SCAN SEP=0 JTAG"
        )
        seq = smu_dtp_ptap_otp_instr_scan_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"ptap_otp_instr_scan incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok}"
        )
