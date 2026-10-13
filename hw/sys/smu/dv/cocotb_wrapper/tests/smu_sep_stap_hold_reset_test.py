# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_stap_hold_reset_test — SEP STAP TMS-Hold parking and 3DCR reset rules."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_stap_hold_reset_test_seq import smu_sep_stap_hold_reset_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_stap_hold_reset_test(smu_base_test):
    """Deselected SEP STAP parks TMS at TMS-Hold; the 3DCR resets on TRST and on TLR."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_sep_stap_hold_reset_test "
            "SMU_WRAPPER_DEBUG_PATHS_009 SEP=1 DTP TAP -> SEP STAP 3DCR"
        )
        seq = smu_sep_stap_hold_reset_test_seq(self)
        await seq.run()
        assert seq.done, "SEP STAP hold/reset scenario incomplete"
