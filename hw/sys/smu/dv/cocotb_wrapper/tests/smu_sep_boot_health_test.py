# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the real SEP DV boot-health firmware under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_boot_health_seq import SmuSepBootHealthSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_boot_health_test(smu_base_test):
    """Require the real SEP firmware to reach its own pass loop."""

    async def run_scenario(self) -> None:
        await SmuSepBootHealthSeq(self).run()
