# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary's payload declares no images at all; the backup boots.

An empty image list is refused after the signature with ``OCA_FAIL_PAYLOAD_TOC``.
Needs ``+esrc_noise_force``: both slots run a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_no_payload_images_base import sep_no_payload_images_primary_base


@pyuvm.test()
class sep_firmware_primary_no_payload_images_test(sep_no_payload_images_primary_base):
    """Plaintext primary TOC image_count is 0 -> refused -> the backup boots."""
