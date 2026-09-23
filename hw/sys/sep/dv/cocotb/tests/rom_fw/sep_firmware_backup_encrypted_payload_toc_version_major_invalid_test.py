# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload declares a bad TOC major version; the ROM halts.

The backup TOC declares major version ``TOC_MAJOR_VERSION + 1``, reached only after decryption.
Needs ``+sep_crypto_edn_force``: the backup runs an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_toc_version_major_invalid_test(
        sep_backup_toc_fail_base):
    """Encrypted backup TOC major_version is 2 -> both slots refused -> halt."""

    toc_field = "version_major"
    encrypted = True
