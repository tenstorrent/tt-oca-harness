# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC firmware smoke under the production SMU wrapper (SEP=1 elaboration)."""

from __future__ import annotations

import pyuvm
from env.smu_boot_scoreboard import SmuSmcBootScoreboard
from seq_lib.smu_smc_smoke_seq import SmuSmcSmokeSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_smoke_test(smu_base_test):
    """Require real SMC ROM execution, scratch activity, and TEST_PASS."""

    def build_phase(self) -> None:
        super().build_phase()
        self.scoreboard = SmuSmcBootScoreboard("smc_boot_scoreboard", self)

    async def run_scenario(self) -> None:
        await SmuSmcSmokeSeq(self, self.scoreboard).run()
