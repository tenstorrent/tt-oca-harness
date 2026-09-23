# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT payload declares a bad TOC major version; the ROM halts.

The backup TOC ``major_version`` is ``TOC_MAJOR_VERSION + 1`` and is refused with
``MANIFEST_ERR_BAD_TOC_VERSION`` after its crypto chain passes; the primary fails as BAD_MAGIC.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_toc_version_major_invalid_test(
        sep_backup_toc_fail_base):
    """Plaintext backup TOC major_version is 2 -> both slots refused -> halt."""

    toc_field = "version_major"
    encrypted = False
