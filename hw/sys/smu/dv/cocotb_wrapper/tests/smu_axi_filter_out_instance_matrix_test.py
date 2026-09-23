# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_filter_out_instance_matrix_test — SMU Tier A outbound instance DECODE."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_filter_out_instance_matrix_test_seq import (
    smu_axi_filter_out_instance_matrix_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_filter_out_instance_matrix_test(smu_base_test):
    """Outbound filter S1 DECODE; S2/S3 need an ext_out peer; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_axi_filter_out_instance_matrix_test "
            "TierA FAB_SMC_025 SEP=1 J2A S1-only"
        )
        seq = smu_axi_filter_out_instance_matrix_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_deferred and seq.s3_deferred, (
            f"out-matrix incomplete s1={seq.s1_ok} s2d={seq.s2_deferred} s3d={seq.s3_deferred}"
        )
