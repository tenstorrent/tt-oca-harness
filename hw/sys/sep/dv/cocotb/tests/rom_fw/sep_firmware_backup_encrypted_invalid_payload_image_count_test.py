# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload declares an out-of-range image count; the ROM halts.

The backup TOC declares 257 images, one past the 256 limit.
Needs ``+sep_crypto_edn_force``: the backup runs an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_invalid_payload_image_count_test(sep_backup_toc_fail_base):
    """Encrypted backup TOC image_count is 257 -> both slots refused -> halt."""

    toc_field = "image_count"
    encrypted = True
