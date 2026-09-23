# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's plaintext payload declares a misaligned image length; the backup boots.

Image 0's length is 0x72D; ``IMAGE_LEN_ALIGN idx=`` separates it from the bounds arm.
Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_toc_entry_fail_base import sep_primary_toc_entry_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_invalid_payload_image_size_test(
        sep_primary_toc_entry_fail_base):
    """Plaintext primary TOC image 0 length is 0x72D -> refused -> the backup boots."""

    entry_defect = ted.SIZE
    encrypted = False
