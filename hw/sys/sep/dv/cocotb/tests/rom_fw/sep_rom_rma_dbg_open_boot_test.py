# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An RMA_SiP part with chiplet debug open boots an unsigned image (PyUVM).

The negative control for the RMA debug-lock tests. With both disable vectors
clear and nothing read-locked, an RMA part stays manifest-optional
(SEP-ROM-SB-020), so the unsigned image ``sep_rom_ot_dma_boot_test`` boots under
``TEST_DEV`` also boots here, announcing ``SBOOT_OFF``.

``FUSE: CHIPLET_DBG_DIS: 0`` is required so the boot is known to have read the
vectors, and ``SBOOT_DBG_LOCK`` is forbidden. Without this control a refusal in
``sep_rom_rma_sip_dbg_lock_refuse_test`` could be the RMA lifecycle refusing
every unsigned image rather than the lock.
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
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_EFUSE_PRELOAD = _EFUSE_DIR / "sep_efuse_lc_rma_sip.toml"


@pyuvm.test()
class sep_rom_rma_dbg_open_boot_test(sep_rom_ot_dma_boot_test):
    """RMA_SiP + debug open + unsigned image: boots unverified."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        "LC=RMA_SIP",
        "FUSE: CHIPLET_DBG_DIS: 0",
        "SBOOT_OFF",
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (DBG_LOCK_MARKER,)

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sip_dis = image.field_int("SIP_DIS")
        sys_dis = image.field_int("SYS_DIS")
        locks = image.field_int("LOCKS")
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x2, f"LC_STATE raw is 0x{lc:x}, expected 0x2 (RMA_SiP)"
        assert not (sip_dis | sys_dis) & _CHIPLET_DBG_BIT, (
            f"CHIPLET_DBG is set (SIP_DIS=0x{sip_dis:x}, SYS_DIS=0x{sys_dis:x}), so "
            f"debug is locked and the part would enforce"
        )
        assert not locks & (_SIP_DIS_READ_LOCK_BIT | _SYS_DIS_READ_LOCK_BIT), (
            f"LOCKS is 0x{locks:x}: a disable vector is read-locked, which counts as debug locked"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the chicken bit would turn secure boot off for "
            f"a different reason"
        )
        self.logger.info(
            "CHK-RMA-STIMULUS: OTP LC raw=0x%x (RMA_SiP), SIP_DIS=0x%x, SYS_DIS=0x%x, "
            "LOCKS=0x%x, SBOOT_DIS=%d",
            lc,
            sip_dis,
            sys_dis,
            locks,
            sboot_dis,
        )
        return image
