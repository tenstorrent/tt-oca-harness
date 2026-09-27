# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED payload declares an out-of-range image count; the backup boots.

The TOC declares 257 images, one past the 256 limit.
Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps and two AES decryptions.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_invalid_payload_image_count_test(sep_primary_toc_fail_base):
    """Encrypted primary TOC image_count is 257 -> refused -> the backup boots."""

    toc_field = "image_count"
    encrypted = True
