# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary manifest carries an IV the payload was not encrypted with.

``decrypt_payload`` hands ``m->encryption_iv`` straight to the AES engine
(``bootrom/prod/src/manifest_crypto.c``), so the manifest decides the CBC
initialisation vector. ``invalid_encryption_iv.bin`` is the golden encrypted image
with the packer's ``packed_encryption_iv`` override applied to the primary
(``Makefile``, ``decrypt_negative_images``): ``pack_encryption`` keeps encrypting
with ``encryption_iv`` and packs the override instead, so the shipped ciphertext
is the golden one and only the field the ROM reads is different. The value is
sixteen ``0xaa`` bytes, chosen so no byte of it collides with the golden IV.

WHAT A WRONG IV CORRUPTS, AND WHY THAT IS ENOUGH. CBC chains each block on the
previous CIPHERTEXT, so an IV affects block 0 alone -- blocks 1 and up recover
correctly. Block 0 is where the TOC header sits, and its first four bytes are the
``PTOC`` identifier (``include/manifest.h``), which is the first thing
``validate_manifest_payload`` reads. So the single corrupted block is exactly the
one the ROM checks, and the run fails with ``MANIFEST_ERR_BAD_TOC_ID``.

That also makes this row the one that distinguishes a lost IV from a wrong key:
the KDF-input and class-key rows corrupt EVERY block, this one corrupts one.

The backup slot is encrypted and golden, so it decrypts and boots in the same run.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps on OTBN plus two AES
decryptions, and AES is EDN client 0.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_encryption_iv_test(sep_decrypt_input_defect_base):
    """Primary manifest IV != encryption IV -> TOC refused -> the backup boots."""

    defect = "iv"
