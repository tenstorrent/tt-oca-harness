# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_filter_in_instance_matrix_test — SMU Tier A inbound instance matrix."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_filter_in_instance_matrix_test_seq import (
    smu_axi_filter_in_instance_matrix_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_filter_in_instance_matrix_test(smu_base_test):
    """Inbound filter S1–S5; SEP=1 J2A + s_axi; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_axi_filter_in_instance_matrix_test TierA FAB_SMC_023 SEP=1 J2A"
        )
        seq = smu_axi_filter_in_instance_matrix_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok and seq.s5_ok, (
            f"in-matrix incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok} s5={seq.s5_ok}"
        )
