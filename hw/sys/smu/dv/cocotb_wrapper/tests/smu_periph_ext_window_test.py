# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_periph_ext_window_test — eFuse bank-control shim and macro AXI-Lite window."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_periph_ext_window_test_seq import smu_periph_ext_window_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_periph_ext_window_test(smu_base_test):
    """The 0xC040_0000 peripheral window over J2A; no Force / no sep_in."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_periph_ext_window_test PERIPH-EXT SEP=0 J2A")
        seq = smu_periph_ext_window_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok, (
            f"periph-ext incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok}"
        )
