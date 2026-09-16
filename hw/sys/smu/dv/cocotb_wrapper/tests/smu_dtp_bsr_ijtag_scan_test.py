# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_bsr_ijtag_scan_test — BSR .select gating (EXTEST / SAMPLE_PRELOAD)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_bsr_ijtag_scan_test_seq import smu_dtp_bsr_ijtag_scan_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_bsr_ijtag_scan_test(smu_base_test):
    """EXTEST/SAMPLE_PRELOAD BSR select; no Force / no sep_in."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_dtp_bsr_ijtag_scan_test TierC DTP-BSR-IJTAG SEP=1 JTAG"
        )
        seq = smu_dtp_bsr_ijtag_scan_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok, (
            f"bsr_ijtag incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok}"
        )
