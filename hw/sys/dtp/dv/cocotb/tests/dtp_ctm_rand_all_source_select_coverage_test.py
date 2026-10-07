# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ctm_rand_all_source_select_coverage_test`."""

from __future__ import annotations

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_xtrig_csr_test_seq import dtp_xtrig_csr_test_seq


@pyuvm.test()
class dtp_ctm_rand_all_source_select_coverage_test(dtp_xtrig_base_test):
    """Per-source CTM select masks read back with no aliasing onto their neighbours."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_csr_test_seq,
            "ctm_all_source_select",
            scenario="ctm_all_source_select",
            specific_knob="DTP_CTM_RAND_ALL_SOURCE_SELECT_COVERAGE_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
