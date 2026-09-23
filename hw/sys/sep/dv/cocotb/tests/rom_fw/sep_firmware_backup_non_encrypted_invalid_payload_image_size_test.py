# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload declares a misaligned image length; the ROM halts.

Image 0 length 0x72D must be refused with ``IMAGE_LEN_ALIGN idx=0x00000000``: the
silent bounds arm returns the same ``MANIFEST_ERR_IMAGE_OOB``, so the code alone is not proof.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_toc_entry_fail_base import sep_backup_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_invalid_payload_image_size_test(
        sep_backup_toc_entry_fail_base):
    """Plaintext backup TOC image 0 length is 0x72D -> both slots refused -> halt."""

    entry_defect = ted.SIZE
    encrypted = False
