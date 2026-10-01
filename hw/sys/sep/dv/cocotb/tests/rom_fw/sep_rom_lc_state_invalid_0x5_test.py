# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""LC_STATE raw 0x5 is invalid, not RMA_CHIPLET (PyUVM).

The other encoding in the ``4'b010?`` gap between RMA_SiP and RMA_CHIPLET. Same
scenario and checks as ``sep_rom_lc_state_invalid_0x4_test``.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_lc_state_invalid_test import EFUSE_DIR, sep_rom_lc_state_invalid_test


@pyuvm.test()
class sep_rom_lc_state_invalid_0x5_test(sep_rom_lc_state_invalid_test):
    """LC_STATE raw 0x5: the ROM must halt as INVALID rather than boot as RMA_CHIPLET."""

    lc_raw = 0x5
    efuse_preload = EFUSE_DIR / "sep_efuse_lc_invalid_0x5.toml"
