# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_sep_dm_sba_test — DTP TAP → SEP debug-module system-bus access."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_sep_dm_sba_test_seq import smu_dtp_sep_dm_sba_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_sep_dm_sba_test(smu_base_test):
    """SEP aperture base, DEMOTE_2 and an egress round trip over the SEP debug system bus."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_sep_dm_sba_test SEP=1 DTP TAP -> SEP DM SBA")
        seq = smu_dtp_sep_dm_sba_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, seq.s4_ok, seq.s5_ok, seq.s6_ok)
        assert all(steps), f"sep_sba incomplete s1..s6={steps}"
