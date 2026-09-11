# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle overrides a manifest that asks for non-secure boot (PyUVM).

FEATURE UNDER TEST. The precedence between the manifest flag and the lifecycle in
``secure_boot_enabled()`` (``manifest_load.c:223-240``): the manifest flag is
honoured only in TEST_DEV and RMA, and ignored under PROD. So the stimulus is
lifecycle PROD, ``SBOOT_DIS = 0``, and a manifest whose ``secure_boot`` flag is
CLEARED. The ROM must still authenticate.

``boot_arguments.flag_args`` sits at manifest offset 1168, outside the TBS region
[0..743] that ``manifest_hash`` covers and the signature is computed over. Clearing
bit 30 therefore leaves a genuinely signed manifest that merely requests non-secure
boot -- exactly the adversary this check exists to stop, and stronger than
re-packing an unsigned image. ``sep_manifest_mutate.verify_layout`` re-derives the
hash afterwards, so layout drift cannot turn this into an accidental
hash-mismatch test.

Distinction from ``sep_firmware_enforced_secure_boot_flow_test``: there the flag is
left set, so lifecycle and manifest agree. Here they disagree and the run
establishes which wins.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

_LC_PROD = "LC=PROD"
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
# The failure signature of this testcase: the ROM honoured the cleared manifest
# flag and skipped authentication in PROD.
_SBOOT_OFF = "SBOOT_OFF"
_SBOOT_DIS_SET = "FUSE: SBOOT_DIS: 1"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)


@pyuvm.test()
class sep_firmware_cntl_secure_boot_flow_test(sep_rom_ot_dma_boot_test):
    """PROD + manifest secure_boot=0: the ROM must enforce secure boot regardless."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _RSA_START,
        _SIG_VALID,
        _CRYPTO_OK,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _SBOOT_OFF,
        _SBOOT_DIS_SET,
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Both slots: the ROM may serve this boot from either, and leaving the
        # backup's flag set would let a failover quietly satisfy the test for the
        # wrong reason.
        for slot in ("primary", "backup"):
            before = mm.get_flag_args(buf, slot)
            assert (before >> mm.FLAG_ARGS_BIT_SECURE_BOOT) & 1 == 1, (
                f"{slot} manifest already has secure_boot=0 (flag_args="
                f"0x{before:08x}); clearing it would be a no-op and the override "
                f"would be untested"
            )
            mm.set_flag_args_bit(buf, slot, mm.FLAG_ARGS_BIT_SECURE_BOOT, False)
            # Proves the mutation left the signed region intact: verify_layout
            # recomputes sha256(TBS) and compares it to the stored manifest_hash.
            mm.verify_layout(buf, slot)
            self.logger.info("CHK-MUTATION: %s", mm.describe(buf, slot))
        return buf

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD). In TEST_DEV a cleared "
            f"manifest flag legitimately disables secure boot, so the override "
            f"under test only exists in PROD/PROD_END"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the chicken bit outranks the lifecycle, so "
            f"secure boot would be off for a different reason than the manifest flag"
        )
        assert bl1_ver == 0, f"BL1_VERSION is 0x{bl1_ver:x}, expected 0 (rollback would mask this)"
        assert revoke == 0, f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0"
        self.logger.info(
            "CHK-SBOOT-STIMULUS: OTP LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            bl1_ver,
            revoke,
        )
        return image
