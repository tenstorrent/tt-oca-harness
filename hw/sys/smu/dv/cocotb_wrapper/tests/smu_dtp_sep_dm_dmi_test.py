# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_sep_dm_dmi_test — DTP TAP → SEP DM DMI IR=5'h11."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_sep_dm_dmi_test(smu_base_test):
    """SEP DM DMI through the DTP TAP; fails if dmi_core_enable is 0."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_sep_dm_dmi_test SEP=1 DTP TAP DMI IR=5'h11")
        seq = smu_dtp_sep_dm_dmi_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok, (
            f"sep_dmi incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok}"
        )
