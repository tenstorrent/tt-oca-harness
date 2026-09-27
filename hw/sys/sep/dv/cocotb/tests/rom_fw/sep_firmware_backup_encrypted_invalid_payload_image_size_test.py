# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload declares a misaligned image length; the ROM halts.

The backup's image 0 length is 0x72D, which is not a multiple of 4.
Needs ``+sep_crypto_edn_force``: the backup runs an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_invalid_payload_image_size_test(sep_backup_toc_entry_fail_base):
    """Encrypted backup TOC image 0 length is 0x72D -> both slots refused -> halt."""

    entry_defect = ted.SIZE
    encrypted = True
