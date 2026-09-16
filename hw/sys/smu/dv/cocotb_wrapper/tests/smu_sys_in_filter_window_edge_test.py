# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sys_in_filter_window_edge_test — page interior OKAY, adjacent page DECERR."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sys_in_filter_window_edge_test_seq import (
    smu_sys_in_filter_window_edge_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sys_in_filter_window_edge_test(smu_base_test):
    """SMN OKAY on filter page interior; DECERR one filter page either side."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_sys_in_filter_window_edge_test TierA SYS-IN page-edge SEP=1 J2A+s_axi"
        )
        seq = smu_sys_in_filter_window_edge_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"filter_window_edge incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok}"
        )
