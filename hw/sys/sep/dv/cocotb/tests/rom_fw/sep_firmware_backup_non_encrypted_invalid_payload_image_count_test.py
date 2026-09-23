# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload declares an out-of-range image count; the ROM halts.

The backup TOC ``image_count`` is 257, one past the limit, and is refused with
``MANIFEST_ERR_TOC_COUNT`` after its crypto chain passes; the primary fails as BAD_MAGIC.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_invalid_payload_image_count_test(
        sep_backup_toc_fail_base):
    """Plaintext backup TOC image_count is 257 -> both slots refused -> halt."""

    toc_field = "image_count"
    encrypted = False
