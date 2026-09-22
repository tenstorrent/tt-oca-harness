# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLASS_KEY fuse is not the key the payload was encrypted under.

``decrypt_payload`` reads 32 bytes from the ``CLASS_KEY`` fuse and runs
``kbkdf_hmac_sha256`` over the manifest's ``encryption_kdf_input`` to derive the
AES key (``bootrom/prod/src/manifest_crypto.c``). The image here is the golden
encrypted image -- its IV, its KDF input and its ciphertext are all the ones that
boot -- and the only thing changed is the fuse: ``CLASS_KEY`` reads zero, which is
what an unprogrammed fuse holds
(``tb/efuse_preloads/efuse_configurations/sep_efuse_lc_prod_bad_class_key.toml``).

The derived key is therefore wrong for every block, the payload decrypts to
garbage without the engine reporting anything, and the boot fails at the TOC
identifier check with ``MANIFEST_ERR_BAD_TOC_ID``. See
``sep_decrypt_input_defect`` for the checks that make that attributable rather
than merely observed.

THIS ROW'S IMAGE HAS AN UNENCRYPTED BACKUP (``invalid_class_key.bin``), and no
other row in this directory does; ``sep_decrypt_input_defect`` states why the fuse
forces that.

That also makes the decryption evidence single-shot: ``DECRYPT_START`` and
``DECRYPT_OK`` must each appear EXACTLY ONCE, the primary's. The IV and KDF-input
rows require two, so no row can satisfy another's checks.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps on OTBN plus one AES
decryption, and AES is EDN client 0.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_decryption_class_key_test(sep_decrypt_input_defect_base):
    """Wrong CLASS_KEY fuse -> garbage plaintext -> TOC refused -> the backup boots."""

    defect = "class_key"
