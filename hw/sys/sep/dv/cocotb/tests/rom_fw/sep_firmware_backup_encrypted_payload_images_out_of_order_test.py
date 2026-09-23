# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED payload lists its images out of order; the ROM halts.

The backup's added image 1 starts at 0x500, below image 0 at 0x1000.
Needs ``+sep_crypto_edn_force``: the backup runs an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_images_out_of_order_test(
        sep_backup_toc_entry_fail_base):
    """Encrypted backup TOC lists image 1 below image 0 -> both slots refused -> halt."""

    entry_defect = ted.ORDER
    encrypted = True
