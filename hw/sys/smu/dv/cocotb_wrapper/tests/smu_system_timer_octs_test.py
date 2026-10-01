# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_system_timer_octs_test — SMU Tier C OCTS primary free-run."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_system_timer_octs_test_seq import smu_system_timer_octs_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_system_timer_octs_test(smu_base_test):
    """SYS-TIMER-OCTS via J2A + tb_timer_count; no Force / no sep_in."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_system_timer_octs_test TierC SYS-TIMER-OCTS SEP=1 J2A"
        )
        seq = smu_system_timer_octs_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"octs incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok} s4={seq.s4_ok}"
        )
        # Pin observe is required on OSS tb_top (tb_timer_count wired).
        assert seq.pin_ok, "tb_timer_count pin observe missing or not advancing"
