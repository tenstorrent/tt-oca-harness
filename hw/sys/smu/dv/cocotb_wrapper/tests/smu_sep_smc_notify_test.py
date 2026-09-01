# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove the SEP outbound egress path, segment by segment."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_smc_notify_seq import SmuSepSmcNotifySeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_smc_notify_test(smu_base_test):
    """Require SEP outbound AW, an SMU-boundary write, then the mailbox PASS."""

    async def run_scenario(self) -> None:
        await SmuSepSmcNotifySeq(self).run()
