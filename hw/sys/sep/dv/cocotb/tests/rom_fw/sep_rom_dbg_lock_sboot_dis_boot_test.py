# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SBOOT_DIS overrides the TEST_DEV debug lock: an unsigned image boots (PyUVM).

The chicken bit is consulted before the device's enforcement view, so it relaxes
the debug-lock requirement exactly as it relaxes PROD enforcement
(SEP-ROM-SB-040). This run presents TEST_DEV with ``SIP_DIS.CHIPLET_DBG`` and
``SBOOT_DIS`` both set, and the unsigned image ``sep_rom_ot_dma_boot_test`` boots
with debug open.

It must boot, announce ``SBOOT_OFF``, and must not print ``SBOOT_DBG_LOCK``,
which [S18] reserves for the case where the lock is what the device's enforcement
rests on. ``FUSE: CHIPLET_DBG_DIS: 1`` is still required, so the boot is known to
have read the lock and overridden it rather than never seen it.
"""

from __future__ import annotations

import os

import pyuvm
from rom_fw.sep_rom_dbg_lock_sip_dis_refuse_test import (
    _CHIPLET_DBG_BIT,
    _EFUSE_DIR,
    DBG_LOCK_MARKER,
    DBG_LOCK_VALUE,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_EFUSE_PRELOAD = _EFUSE_DIR / "sep_efuse_lc_test_dev_chiplet_dbg_sboot_dis.toml"


@pyuvm.test()
class sep_rom_dbg_lock_sboot_dis_boot_test(sep_rom_ot_dma_boot_test):
    """TEST_DEV + SIP_DIS.CHIPLET_DBG + SBOOT_DIS + unsigned image: boots unverified."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        "LC=TEST_DEV",
        "FUSE: SBOOT_DIS: 1",
        DBG_LOCK_VALUE,
        "SBOOT_OFF",
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (DBG_LOCK_MARKER,)

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sip_dis = image.field_int("SIP_DIS")
        sboot_dis = image.field_int("SBOOT_DIS")
        assert lc == 0x0, f"LC_STATE raw is 0x{lc:x}, expected 0x0 (TEST_DEV)"
        assert sip_dis & _CHIPLET_DBG_BIT, (
            f"SIP_DIS is 0x{sip_dis:x}: CHIPLET_DBG is clear, so there is no lock to "
            f"override and this run would duplicate sep_rom_ot_dma_boot_test"
        )
        assert sboot_dis == 0x1, (
            f"SBOOT_DIS is 0x{sboot_dis:08x}, expected 0x00000001 (chicken bit only)"
        )
        self.logger.info(
            "CHK-DBG-LOCK-STIMULUS: OTP LC raw=0x%x (TEST_DEV), SIP_DIS=0x%x, SBOOT_DIS=0x%x",
            lc,
            sip_dis,
            sboot_dis,
        )
        return image
