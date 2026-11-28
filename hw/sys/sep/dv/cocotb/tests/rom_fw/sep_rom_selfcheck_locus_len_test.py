# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The validated manifest length passes the end of SEP SRAM; 0xF004.

The contract, stimulus and checks are in sep_rom_selfcheck_reverify_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_selfcheck_reverify_base import SRAM_SIZE, sep_rom_locus_flip_base


@pyuvm.test()
class sep_rom_selfcheck_locus_len_test(sep_rom_locus_flip_base):
    data_mask = SRAM_SIZE

    def target(self) -> int:
        return self.img.syms["g_gate_manifest_len"]
