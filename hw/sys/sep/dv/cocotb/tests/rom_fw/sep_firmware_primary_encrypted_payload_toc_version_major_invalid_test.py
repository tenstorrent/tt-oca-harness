# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED payload declares a bad TOC major version; the backup boots.

The defect goes into the plaintext and is re-encrypted: the ROM checks the TOC only
after decryption. Needs ``+sep_crypto_edn_force`` for RSA-3072 and AES.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_toc_version_major_invalid_test(
    sep_primary_toc_fail_base
):
    """Encrypted primary TOC major_version is 2 -> refused -> the backup boots."""

    toc_field = "version_major"
    encrypted = True
