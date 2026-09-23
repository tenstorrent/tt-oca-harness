# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the production ROM from the RSA-3072-signed SPI image and check that OTBN verified it.

A zero OTP gives TEST_DEV with sboot_dis=0, so the manifest's secure_boot flag enables verification.
``+sep_crypto_edn_force`` grants OTBN's EDN handshakes.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
_SBOOT_OFF = "SBOOT_OFF"


@pyuvm.test()
class sep_rom_ot_secure_boot_test(sep_rom_ot_dma_boot_test):
    """Boot from the signed SPI image and verify the RSA-3072 path really ran."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _RSA_START,
        _SIG_VALID,
        _CRYPTO_OK,
    )
    # SBOOT_OFF means the ROM silently fell back to the unsigned path and still booted.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (_SBOOT_OFF,)
