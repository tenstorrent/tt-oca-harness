# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT payload lists its images out of order; the backup boots.

The ROM must refuse image 1 at offset 0x500, below image 0's 0x1000, with
``IMAGE_ORDER_BAD`` and ``MANIFEST_ERR_IMAGE_OVERLAP``, then fail over to the backup.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_toc_entry_fail_base import sep_primary_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_payload_images_out_of_order_test(
        sep_primary_toc_entry_fail_base):
    """Plaintext primary TOC lists image 1 below image 0 -> refused -> backup boots."""

    entry_defect = ted.ORDER
    encrypted = False
