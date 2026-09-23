# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with SBOOT_DIS set: the fuse overrides the lifecycle and secure boot is skipped.

The eFuse must come from the +sep_efuse_preload file: the OTP model loads it at
t=0, before the test body can write it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm

from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

_SBOOT_OFF = "SBOOT_OFF"
# Without this echo, a preload that failed to stage looks like a working fuse.
_SBOOT_DIS_SET = "FUSE: SBOOT_DIS: 1"
_LC_PROD = "LC=PROD"
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod_sboot_dis.toml"
)


@pyuvm.test()
class sep_firmware_device_cntl_non_secure_boot_flow_test(sep_rom_ot_dma_boot_test):
    """PROD + SBOOT_DIS=1: the ROM must skip secure boot and still reach BL1."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _SBOOT_DIS_SET, _LC_PROD, _SBOOT_OFF,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _RSA_START, _SIG_VALID, _CRYPTO_OK,
    )

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), (
            f"eFuse preload missing: {_EFUSE_PRELOAD}"
        )
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        # select_efuse_image() falls back to a random image when the plusarg is absent.
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert sboot_dis == 1, (
            f"SBOOT_DIS is {sboot_dis}, expected 1: the testlist must pass "
            f"+sep_efuse_preload={_EFUSE_PRELOAD}"
        )
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): without PROD the "
            f"manifest flag could explain a non-secure boot and the fuse override "
            f"would be untested"
        )
        self.logger.info(
            "CHK-SBOOT-STIMULUS: OTP image LC raw=0x%x (PROD), SBOOT_DIS=%d", lc, sboot_dis
        )
        return image
