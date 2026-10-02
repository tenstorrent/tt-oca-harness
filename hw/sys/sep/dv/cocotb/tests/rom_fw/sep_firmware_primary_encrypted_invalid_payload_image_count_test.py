# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC declares 257 images, more than the payload holds; the backup boots.

The count-fit rule refuses the TOC with ``OCA_FAIL_PAYLOAD_TOC`` before the build-time
cap ``OCA_TOC_MAX_IMAGES`` applies. Needs ``+esrc_noise_force``: two RSA and AES runs.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_invalid_payload_image_count_test(sep_primary_toc_fail_base):
    """Encrypted primary TOC image_count is 257 -> refused -> the backup boots."""

    toc_field = td.IMAGE_COUNT
    encrypted = True
