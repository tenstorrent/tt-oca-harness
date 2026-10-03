# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A debug-locked TEST_DEV part boots a validly signed image (PyUVM).

The positive half of SEP-ROM-SB-025: enforcement on a debug-locked TEST_DEV part
refuses unsigned code, and still boots signed code through the full RSA-3072
chain. ``sep_rom_ot_secure_boot_test`` with the OTP swapped for TEST_DEV plus
``SIP_DIS.CHIPLET_DBG``.

WHAT THIS DOES NOT ESTABLISH. The shipped image sets ``secure_boot_control``, and
the manifest's own request settles the precedence before the device is asked, so
the crypto chain running is not evidence of the debug lock (see
``sep_firmware_enforced_secure_boot_flow_test`` for the same caveat under PROD).
The refusal members, which clear that flag, are the evidence. What this adds is
that a debug-locked part is not simply unbootable, and that [S18] reports the
lock on a boot that succeeds.
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
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test


@pyuvm.test()
class sep_rom_dbg_lock_secure_boot_test(sep_rom_ot_secure_boot_test):
    """TEST_DEV + SIP_DIS.CHIPLET_DBG + signed image: RSA-3072 verifies, BL1 entered."""

    efuse_preload = _EFUSE_DIR / "sep_efuse_lc_test_dev_chiplet_dbg_sip.toml"
    expected_lc_raw = 0x0
    lc_marker = "LC=TEST_DEV"

    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        lc_marker,
        DBG_LOCK_VALUE,
        DBG_LOCK_MARKER,
    )

    def build_efuse_image(self):
        preload = self.efuse_preload
        assert os.path.isfile(preload), f"eFuse preload missing: {preload}"
        image = self.select_efuse_image(default_preload=preload)
        lc = image.lc_raw()
        sip_dis = image.field_int("SIP_DIS")
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == self.expected_lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x} ({self.lc_marker})"
        )
        assert sip_dis & _CHIPLET_DBG_BIT, (
            f"SIP_DIS is 0x{sip_dis:x}: CHIPLET_DBG is clear, so debug is open"
        )
        assert sboot_dis == 0, f"SBOOT_DIS is {sboot_dis}: the chicken bit would override the lock"
        self.logger.info(
            "CHK-DBG-LOCK-STIMULUS: OTP LC raw=0x%x (%s), SIP_DIS=0x%x, SBOOT_DIS=%d",
            lc,
            self.lc_marker,
            sip_dis,
            sboot_dis,
        )
        return image
