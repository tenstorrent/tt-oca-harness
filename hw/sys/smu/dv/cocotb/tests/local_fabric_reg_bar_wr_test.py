# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""local_fabric_reg_bar_wr_test — SMU Tier A fabric config CSR delivery."""

from __future__ import annotations

import pyuvm

from seq_lib.local_fabric_reg_bar_wr_test_seq import local_fabric_reg_bar_wr_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class local_fabric_reg_bar_wr_test(smu_base_test):
    """FAB_SMC_032 delivery-only via J2A; no Force / no sep_in."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE local_fabric_reg_bar_wr_test "
            "TierA FAB_SMC_032 SEP=0 J2A"
        )
        seq = local_fabric_reg_bar_wr_test_seq(self)
        await seq.run()
        assert seq.s1_ok and len(seq.observed) == 6, (
            f"local_fabric incomplete s1={seq.s1_ok} "
            f"observed={seq.observed}"
        )
