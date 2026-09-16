# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the real SEP DV sanity firmware under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_sanity_seq import SmuSepSanitySeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_sanity_test(smu_base_test):
    """Require the SEP to pass its own HMAC and KMAC known-answer tests."""

    async def run_scenario(self) -> None:
        await SmuSepSanitySeq(self).run()
