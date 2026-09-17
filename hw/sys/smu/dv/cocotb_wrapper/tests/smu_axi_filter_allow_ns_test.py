# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_filter_allow_ns_test — SMU Tier A allow_ns (SEP=1 J2A + s_axi)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_filter_allow_ns_test_seq import (
    smu_axi_filter_allow_ns_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_filter_allow_ns_test(smu_base_test):
    """Inbound allow_ns S1/S2/S3; no Force / no sep_in."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_filter_allow_ns_test TierA allow_ns SEP=1 J2A")
        seq = smu_axi_filter_allow_ns_test_seq(self)
        await seq.run()
        assert seq.secure_ok and seq.ns_block_ok and seq.dual_ok and seq.clear_ok, (
            f"allow_ns incomplete s1s={seq.secure_ok} s1n={seq.ns_block_ok} "
            f"s2={seq.dual_ok} s3={seq.clear_ok}"
        )
