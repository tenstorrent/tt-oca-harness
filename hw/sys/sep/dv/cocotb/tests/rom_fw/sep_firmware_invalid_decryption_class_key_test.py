# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLASS_KEY fuse is not the key the payload was encrypted under.

The fuse reads zero, so every block decrypts to garbage and the TOC ID check fails.
The backup slot is unencrypted. Needs +sep_crypto_edn_force (AES is EDN client 0).
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_decryption_class_key_test(sep_decrypt_input_defect_base):
    """Wrong CLASS_KEY fuse -> garbage plaintext -> TOC refused -> the backup boots."""

    defect = "class_key"
