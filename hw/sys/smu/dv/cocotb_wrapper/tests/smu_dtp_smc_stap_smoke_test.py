# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_smc_stap_smoke_test — DTP-SMC-STAP TRST + TAP_3DCR select."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_smc_stap_smoke_test_seq import smu_dtp_smc_stap_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_smc_stap_smoke_test(smu_base_test):
    """SMC STAP TRST + TAP_3DCR via tdo_oen; no Force / no sep_in."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_dtp_smc_stap_smoke_test TierC DTP-SMC-STAP SEP=1 JTAG"
        )
        seq = smu_dtp_smc_stap_smoke_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok, (
            f"smc_stap incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok}"
        )
