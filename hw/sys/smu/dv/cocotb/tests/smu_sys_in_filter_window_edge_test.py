# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sys_in_filter_window_edge_test — page interior OKAY, ±4B DECERR."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sys_in_filter_window_edge_test_seq import (
    smu_sys_in_filter_window_edge_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sys_in_filter_window_edge_test(smu_base_test):
    """SMN OKAY on filter page edges; DECERR one beat outside."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_sys_in_filter_window_edge_test TierA SYS-IN page-edge SEP=0 J2A+s_axi"
        )
        seq = smu_sys_in_filter_window_edge_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok, (
            f"filter_window_edge incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok}"
        )
