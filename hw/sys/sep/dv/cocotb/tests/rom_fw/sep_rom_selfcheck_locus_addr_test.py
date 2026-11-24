# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The recorded manifest address leaves the SRAM base after [S23]; 0xF004.

The contract, stimulus and checks are in sep_rom_selfcheck_reverify_base.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_selfcheck_reverify_base import manifest_addr_field, sep_rom_locus_flip_base


@pyuvm.test()
class sep_rom_selfcheck_locus_addr_test(sep_rom_locus_flip_base):
    data_mask = 1 << 4

    def target(self) -> int:
        return manifest_addr_field(self.img)
