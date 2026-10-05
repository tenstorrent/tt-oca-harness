# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""LC_STATE raw 0x4 is invalid, not RMA_CHIPLET.

The lifecycle controller decodes RMA_CHIPLET as ``4'b011?``
(``hw/sys/sep/rtl/sep_lifecycle_ctrl.sv``), so raw ``0x4`` and ``0x5`` fall to its
INVALID arm. The ROM must reach the same verdict (SEP-ROM-FUSE-020): on these
encodings a ROM that decoded RMA_CHIPLET would boot with secure boot optional on
a part the hardware treats as dead.

The scenario and checks are ``sep_rom_lc_state_invalid_test``'s, including the
SMC hold and the requirement that no state name is decoded.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_lc_state_invalid_test import EFUSE_DIR, sep_rom_lc_state_invalid_test


@pyuvm.test()
class sep_rom_lc_state_invalid_0x4_test(sep_rom_lc_state_invalid_test):
    """LC_STATE raw 0x4: the ROM must halt as INVALID rather than boot as RMA_CHIPLET."""

    lc_raw = 0x4
    efuse_preload = EFUSE_DIR / "sep_efuse_lc_invalid_0x4.toml"
