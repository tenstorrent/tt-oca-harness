# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the real SEP DV module-matrix firmware under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_modules_seq import SmuSepModulesSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_modules_test(smu_base_test):
    """Require every built SEP module stage to clear its own on-chip check."""

    async def run_scenario(self) -> None:
        await SmuSepModulesSeq(self).run()
