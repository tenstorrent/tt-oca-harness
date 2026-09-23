# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT payload declares a bad TOC major version; the backup boots.

The ROM must refuse TOC ``major_version`` 2 with ``MANIFEST_ERR_BAD_TOC_VERSION``
after the primary's signature verifies, then fail over to the backup.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_payload_toc_version_major_invalid_test(
        sep_primary_toc_fail_base):
    """Plaintext primary TOC major_version is 2 -> refused -> the backup boots."""

    toc_field = "version_major"
    encrypted = False
