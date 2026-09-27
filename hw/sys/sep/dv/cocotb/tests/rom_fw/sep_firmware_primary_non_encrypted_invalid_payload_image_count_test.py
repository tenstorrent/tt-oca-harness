# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's plaintext payload declares an out-of-range image count; the backup boots.

The primary's TOC ``image_count`` is 257, one past the bound, so it fails TOC_COUNT.
Needs ``+sep_crypto_edn_force``: both slots run a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_invalid_payload_image_count_test(
    sep_primary_toc_fail_base
):
    """Plaintext primary TOC image_count is 257 -> refused -> the backup boots."""

    toc_field = "image_count"
    encrypted = False
