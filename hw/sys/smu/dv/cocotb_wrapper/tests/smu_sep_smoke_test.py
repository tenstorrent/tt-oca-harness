# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP RTL boot-readiness smoke under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from env.smu_boot_scoreboard import SmuSepBootScoreboard
from seq_lib.smu_sep_smoke_seq import SmuSepSmokeSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_smoke_test(smu_base_test):
    """Require real SEP reset, boot-ROM fetch, ICCM execution, DCCM stores."""

    def build_phase(self) -> None:
        super().build_phase()
        self.scoreboard = SmuSepBootScoreboard("sep_boot_scoreboard", self)

    async def run_scenario(self) -> None:
        await SmuSepSmokeSeq(self, self.scoreboard).run()
