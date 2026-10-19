# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_sep_ic_reset_effect_test — IC_RESET SEP slice override of the SEP main reset."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_sep_ic_reset_effect_test_seq import (
    smu_dtp_sep_ic_reset_effect_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_sep_ic_reset_effect_test(smu_base_test):
    """sep_reset_n override engage, Test-Logic-Reset with reset_hold, release and isolation."""

    use_shared_env = True
    required_evidence = (
        "CHK-DBG-IC-SEP-HOLD-TLR",
        "CHK-DBG-IC-SEP-ISOLATION",
        "CHK-DBG-IC-SEP-POSITION",
        "CHK-DBG-IC-SEP-QUIESCE",
        "CHK-DBG-IC-SEP-RELEASE",
        "CHK-DBG-IC-SEP-SETUP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_dtp_sep_ic_reset_effect_test SEP=1 JTAG")
        await smu_dtp_sep_ic_reset_effect_test_seq(self).run()
