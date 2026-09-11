# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP LC handoff consumer and SMC PVT-arm producer under the SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_lc_handoff_seq import SmuSepLcHandoffSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_lc_handoff_test(smu_base_test):
    """Classify the LC-handoff pair by the SEP terminal loop."""

    async def run_scenario(self) -> None:
        await SmuSepLcHandoffSeq(self).run()
