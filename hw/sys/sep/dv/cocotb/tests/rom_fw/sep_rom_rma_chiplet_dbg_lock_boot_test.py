# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A debug-locked RMA_CHIPLET part still boots an unsigned image.

SEP-ROM-SB-025 applies the chiplet debug lock to TEST_DEV and RMA_SiP only:
``lc_state_follows_debug_lock()`` (``bootrom/prod/src/lifecycle.c``) excludes
RMA_CHIPLET, which stays manifest-optional whatever the disable vectors say.

This run presents RMA_CHIPLET (raw ``0x6``) with ``CHIPLET_DBG`` set in ``SIP_DIS`` --
the same vector that makes ``sep_rom_rma_dbg_lock_secure_boot_test``'s RMA_SiP part
enforce -- and ``SBOOT_DIS`` clear, and boots the unsigned image
``sep_rom_ot_dma_boot_test`` boots under TEST_DEV.

It must boot and announce ``SBOOT_OFF``, and must not print ``SBOOT_DBG_LOCK``.
``FUSE: CHIPLET_DBG_DIS: 1`` is required so the boot is known to have read the lock
and declined to apply it, rather than never having seen it.
"""

from __future__ import annotations

import os

import pyuvm
from rom_fw.sep_rom_dbg_lock_sip_dis_refuse_test import (
    _CHIPLET_DBG_BIT,
    _EFUSE_DIR,
    _SIP_DIS_READ_LOCK_BIT,
    _SYS_DIS_READ_LOCK_BIT,
    DBG_LOCK_MARKER,
    DBG_LOCK_VALUE,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_EFUSE_PRELOAD = _EFUSE_DIR / "sep_efuse_lc_rma_chiplet_chiplet_dbg_sip.toml"


@pyuvm.test()
class sep_rom_rma_chiplet_dbg_lock_boot_test(sep_rom_ot_dma_boot_test):
    """RMA_CHIPLET + SIP_DIS.CHIPLET_DBG + unsigned image: boots unverified."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        "LC=RMA_CHIPLET",
        DBG_LOCK_VALUE,
        "SBOOT_OFF",
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (DBG_LOCK_MARKER,)

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sip_dis = image.field_int("SIP_DIS")
        locks = image.field_int("LOCKS")
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x6, f"LC_STATE raw is 0x{lc:x}, expected 0x6 (RMA_CHIPLET)"
        assert sip_dis & _CHIPLET_DBG_BIT, (
            f"SIP_DIS is 0x{sip_dis:x}: CHIPLET_DBG is clear, so there is no lock for "
            f"RMA_CHIPLET to ignore and this run would duplicate an open-debug boot"
        )
        assert not locks & (_SIP_DIS_READ_LOCK_BIT | _SYS_DIS_READ_LOCK_BIT), (
            f"LOCKS is 0x{locks:x}: a read-locked vector is a second lock source"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the chicken bit would turn secure boot off for "
            f"a different reason"
        )
        self.logger.info(
            "CHK-RMA-STIMULUS: OTP LC raw=0x%x (RMA_CHIPLET), SIP_DIS=0x%x, LOCKS=0x%x, "
            "SBOOT_DIS=%d",
            lc,
            sip_dis,
            locks,
            sboot_dis,
        )
        return image
