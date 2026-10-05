# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Device control vs. a manifest that asks to be verified: the manifest wins.

Secure boot is decided by a precedence
(``bootrom/prod/tools/tt-oca-manifest/validators/oca/lib/secure_boot.c``)::

    signed secure_boot_control[0] set -> ENFORCE   (checked first)
    device disable (SBOOT_DIS, LC)    -> DISABLE   (only if the manifest is silent)
    device enforcement view           -> ENFORCE   (fail-safe on an odd answer)

This pins the first input against the second: PROD with ``SBOOT_DIS = 1`` and the ordinary signed
image, whose ``secure_boot_control`` bit 0 is set. Secure boot must stay on, so the full RSA-3072
chain runs and ``SBOOT_OFF`` is never printed. An image built to be verified can only boot
verified; the fuse governs only images with no signed request (SEP-ROM-SB-040). PROD isolates the
precedence: under TEST_DEV the lifecycle alone would not enforce.

The eFuse comes from a committed preload: the OTP model reads it at t=0, before the cocotb body
runs. The testlist passes ``+sep_efuse_preload=<path>``, which ``dv_sim_prestage.stage()`` and
``select_efuse_image()`` both honour, so the sensed fuses and the golden are the same file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

# Emitted only when the ROM decides secure boot is OFF (rom_main.c).
_SBOOT_OFF = "SBOOT_OFF"
# lifecycle.c prints the fuse it read, in decimal. This is the evidence
# that the fuse the testcase relies on was actually sensed as 1 -- without it a
# preload that failed to stage would look identical to a working chicken bit.
_SBOOT_DIS_SET = "FUSE: SBOOT_DIS: 1"
# lifecycle.c decodes the sensed LC_STATE to one of these. Requiring PROD is what
# makes the override meaningful rather than incidental.
_LC_PROD = "LC=PROD"
# Crypto-path markers that must appear: the signed request keeps secure boot on.
_PUBK_AUTH = "PUBK_AUTHORIZED"
_RSA_EXEC = "RSA_EXEC"
_RSA_OK = "RSA_VERIFY_OK"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_sboot_dis.toml"
)


@pyuvm.test()
class sep_firmware_device_cntl_non_secure_boot_flow_test(sep_rom_ot_dma_boot_test):
    """PROD + SBOOT_DIS=1 + signed request: secure boot stays on and BL1 is reached."""

    flash_image = SECURE_FLASH_IMAGE
    # Inherit the SPI-path markers (BOOT_SPI / MANIFEST_SRC / MANIFEST_OK) so the
    # transport is still pinned down, then add the device-control evidence.
    # SBOOT_DIS and PROD are the stimulus, so both are asserted present; the
    # crypto markers are the outcome, and they say the fuse did not downgrade the
    # signed request.
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _SBOOT_DIS_SET,
        _LC_PROD,
        _PUBK_AUTH,
        _RSA_EXEC,
        _RSA_OK,
    )
    # SBOOT_OFF would mean the ROM took the fuse as decisive and skipped
    # verification, which is the bypass this precedence exists to prevent.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (_SBOOT_OFF,)

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        # Guard the stimulus. select_efuse_image() falls back to a seeded random
        # image when the plusarg is absent. A random image would not set
        # SBOOT_DIS, so the precedence would be untested.
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK
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
