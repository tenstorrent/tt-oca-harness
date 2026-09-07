# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM SECURE boot over the OpenTitan SPI host (PyUVM) -- RSA-3072 on OTBN.

The signed sibling of ``sep_rom_ot_dma_boot_test``. Identical ROM, identical SPI
transport (OpenTitan spi_host, SECURE_DMA drain, OcahSpiFlash BFM); the only
change is the flash image, which carries an RSA-3072 PKCS#1 v1.5 signature over
the manifest (``make secure_boot_spi``, dev0 key from the tt-boot-manifest
submodule, digest pinned in key_digests.c slot 0).

That one swap turns on a whole code path the non-secure test never reaches:

    manifest_load.c  secure_boot_enabled()  -- manifest's secure_boot flag
      -> manifest_crypto.c                  -- version rollback, key revocation
        -> rsa_verify.c                     -- loads modulus/signature into OTBN
          -> OTBN rsa_3072_app              -- signature^e mod n (Montgomery)
        -> PKCS#1 v1.5 unpad, digest compare
      -> payload SHA-256 -> BL1 jump

`secure_boot_enabled()` gates on `sboot_dis` (eFuse), the manifest flag, and the
lifecycle state: PROD/PROD_END always enforce, TEST_DEV/RMA enforce only when the
manifest asks. A zero OTP gives TEST_DEV with sboot_dis=0, and the signed manifest
sets the flag -- so this test needs no special eFuse image, unlike the reference
flow which ships a PROD preload to force it.

NOTE ON ENTROPY: this run does NOT exercise the entropy chain. OTBN cannot execute
until URND is reseeded, and the boot flow does not bring up
entropy_source/CSRNG/EDN, so the testlist opts into +sep_crypto_edn_force to grant
OTBN's EDN handshakes directly. That supplies entropy only -- the RSA assertions
below are untouched, so a pass still means the signature genuinely verified.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

# Emitted by manifest_crypto.c / rsa_verify.c only on the signed path.
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
# Printed when the ROM decides secure boot is OFF -- the non-secure test's normal
# output, and a silent-downgrade signature here.
_SBOOT_OFF = "SBOOT_OFF"


@pyuvm.test()
class sep_rom_ot_secure_boot_test(sep_rom_ot_dma_boot_test):
    """Boot from the signed SPI image and verify the RSA-3072 path really ran."""

    flash_image = SECURE_FLASH_IMAGE
    # Inherit the SPI-path markers, then demand the crypto ones. RSA_VERIFY_START
    # proves OTBN was actually driven (not just that the manifest parsed);
    # SIG_VALID and CRYPTO_VALIDATE_OK prove the signature check reached a verdict
    # and that verdict was "valid".
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _RSA_START,
        _SIG_VALID,
        _CRYPTO_OK,
    )
    # SBOOT_OFF must NOT appear: it would mean the ROM silently downgraded to the
    # unsigned path and booted anyway, which passes every other check while
    # verifying no crypto at all.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (_SBOOT_OFF,)
