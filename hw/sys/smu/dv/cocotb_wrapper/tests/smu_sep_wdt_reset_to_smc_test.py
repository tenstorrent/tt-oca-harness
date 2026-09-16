# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP WDT bark-then-bite firmware under the SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_wdt_reset_to_smc_seq import SmuSepWdtResetToSmcSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_wdt_reset_to_smc_test(smu_base_test):
    """Classify the WDT-reset image by the SEP terminal loop."""

    async def run_scenario(self) -> None:
        await SmuSepWdtResetToSmcSeq(self).run()
