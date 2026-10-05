# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM boot from an AES-256-CBC encrypted OCA payload, with an OTP-derived key.

The image is also signed: the format forbids encryption without secure boot. After
manifest validation, ``plat_decrypt_payload()`` (``oca_platform.c``) reads the CLASS_KEY
eFuse secret, derives the key on the HMAC core (``kdf.c``, SP 800-108r1 CTR-HMAC-SHA-256),
decrypts with ``aes_cbc_decrypt()`` (``aes_driver.c``) and strips the PKCS#7 padding. The
library then hashes the plaintext, so ``PAYLOAD_OK`` holds only for a bit-exact key.

Difference from ``sep_firmware_encrypted_boot_test``: this test writes CLASS_KEY into the
default eFuse image (``set_words``) and checks the console markers only. The sibling boots
the same image from the ``sep_efuse_class_key.toml`` preload and also checks the attempt
order.

The CLASS_KEY words must match ``encryption_secret`` in
``bootrom/prod/configs/oca_encrypted_boot_test.yaml``. A wrong word order still derives a
key, and the failure then shows as a payload hash-chain error.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
ENCRYPTED_FLASH_IMAGE = os.path.join(
    _SEP_ROOT, "bootrom", "prod", "build", "oca_encrypted_boot.bin"
)

# The 32-byte secret 00 01 02 ... 1f, as 8 x 32-bit OTP words: word[0] holds
# bits[31:0], so each word is four consecutive secret bytes read little-endian.
_CLASS_KEY_WORDS = [
    0x03020100,
    0x07060504,
    0x0B0A0908,
    0x0F0E0D0C,
    0x13121110,
    0x17161514,
    0x1B1A1918,
    0x1F1E1D1C,
]

# Printed by plat_decrypt_payload() once the AES engine has drained and the
# PKCS#7 padding stripped clean.
_DECRYPT_OK = "DECRYPT_OK"
# The three ways that callback can fail. Forbidding them individually rather
# than relying on the boot failing is what separates "decrypted correctly" from
# "never tried": an unprovisioned CLASS_KEY reads as all-zeroes, which is a
# refusal the ROM makes deliberately (DECRYPT_CLASS_KEY_EMPTY) rather than a
# key it would derive from.
_DECRYPT_NO_SECRET = "DECRYPT_NO_SECRET"
_DECRYPT_KEY_EMPTY = "DECRYPT_CLASS_KEY_EMPTY"

# A crypto op the IP refuses to start leaves STATUS.hmac_idle asserted, which a
# completion poll reads as success -- so a garbage digest, and therefore a
# garbage AES key, would reach decryption looking like a clean run. These are
# what check_no_error()/check_no_alert() print when that happens.
_CRYPTO_REJECTED = (
    "KDF_HMAC_FAIL",
    "HMAC_ERR_CODE=",
    "HMAC_START_REJECTED",
    "HMAC_OP_REJECTED",
    "SHA_START_REJECTED",
    "SHA_OP_REJECTED",
    "AES_INIT_BUSY",
)
# This image is valid, so any manifest rejection means a check refused
# something it should accept.
_MANIFEST_ERR = "MANIFEST_ERR="
_KDF_FAIL = "KDF_FAIL"
_AES_DEC_FAIL = "AES_DEC_FAIL"


@pyuvm.test()
class sep_rom_oca_encrypted_boot_test(sep_rom_ot_secure_boot_test):
    """Decrypt an AES-256 payload with an OTP-derived key and boot it."""

    flash_image = ENCRYPTED_FLASH_IMAGE
    # Inherit the signed test's RSA/authorization markers -- this image is signed
    # as well -- and add the decryption evidence. The inherited PAYLOAD_OK carries
    # the real weight here: it is printed only after the hash chain over the
    # DECRYPTED bytes matched, so it is what rules out a wrong-key derivation.
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (_DECRYPT_OK,)
    forbidden_markers = (
        sep_rom_ot_secure_boot_test.forbidden_markers
        + (
            _DECRYPT_NO_SECRET,
            _DECRYPT_KEY_EMPTY,
            _KDF_FAIL,
            _AES_DEC_FAIL,
            _MANIFEST_ERR,
        )
        + _CRYPTO_REJECTED
    )

    def build_efuse_image(self) -> SepEfuseImage:
        img = super().build_efuse_image()
        img.set_words("CLASS_KEY", _CLASS_KEY_WORDS)
        return img
