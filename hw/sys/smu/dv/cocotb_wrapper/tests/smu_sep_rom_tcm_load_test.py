# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the SEP with no TCM preload and let it load its own ICCM."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_rom_tcm_load_seq import SmuSepRomTcmLoadSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_rom_tcm_load_test(smu_base_test):
    """Require the SEP to DMA code into its own ICCM and execute it."""

    async def run_scenario(self) -> None:
        await SmuSepRomTcmLoadSeq(self).run()
