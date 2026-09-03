# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Check SEP output-remap programming under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_remap_seq import SmuSepRemapSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_remap_test(smu_base_test):
    """Require the SEP to land the golden remap offsets, not merely to run."""

    async def run_scenario(self) -> None:
        await SmuSepRemapSeq(self).run()
