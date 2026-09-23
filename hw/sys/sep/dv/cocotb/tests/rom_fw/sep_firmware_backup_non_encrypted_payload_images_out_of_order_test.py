# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload lists its images out of order; the ROM halts.

Image 1 offset 0x500 lies below image 0 at 0x1000 and is refused with
``IMAGE_ORDER_BAD idx=0x00000001``; the primary is refused as BAD_MAGIC.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_images_out_of_order_test(
        sep_backup_toc_entry_fail_base):
    """Plaintext backup TOC lists image 1 below image 0 -> both slots refused -> halt."""

    entry_defect = ted.ORDER
    encrypted = False
