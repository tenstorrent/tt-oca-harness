# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the real SEP DV sep_smu_aes firmware under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_aes_seq import SmuSepAesSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_aes_test(smu_base_test):
    async def run_scenario(self) -> None:
        await SmuSepAesSeq(self).run()
