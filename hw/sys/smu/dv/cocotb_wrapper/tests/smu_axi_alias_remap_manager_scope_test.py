# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_alias_remap_manager_scope_test — SMU Tier A alias-remap (S3 LIVE)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_alias_remap_manager_scope_test_seq import (
    smu_axi_alias_remap_manager_scope_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_alias_remap_manager_scope_test(smu_base_test):
    """FAB_SMC_018 S3 J2A+SPM; S1/S2/S4/S5 are not covered; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_axi_alias_remap_manager_scope_test "
            "TierA FAB_SMC_018 SEP=1 J2A S3-only"
        )
        seq = smu_axi_alias_remap_manager_scope_test_seq(self)
        await seq.run()
        assert (
            seq.s3_ok
            and seq.s1_deferred
            and seq.s2_deferred
            and seq.s4_deferred
            and seq.s5_deferred
        ), (
            f"alias-remap incomplete s3={seq.s3_ok} "
            f"d1={seq.s1_deferred} d2={seq.s2_deferred} "
            f"d4={seq.s4_deferred} d5={seq.s5_deferred}"
        )
