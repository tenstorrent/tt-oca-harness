# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the real SEP DV dma firmware under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_dma_seq import SmuSepDmaSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_dma_test(smu_base_test):
    """Require the SEP dma firmware to clear its own on-chip checks."""

    async def run_scenario(self) -> None:
        await SmuSepDmaSeq(self).run()
