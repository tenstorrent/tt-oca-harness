# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_io_stap_smoke_test — DTP-IO-STAP host TCK observe."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_io_stap_smoke_test_seq import smu_dtp_io_stap_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_io_stap_smoke_test(smu_base_test):
    """IO STAP TCK fanout during PTAP scans; no Force / no sep_in."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_io_stap_smoke_test TierC DTP-IO-STAP SEP=1 JTAG")
        seq = smu_dtp_io_stap_smoke_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok, f"io_stap incomplete s1={seq.s1_ok} s2={seq.s2_ok}"
