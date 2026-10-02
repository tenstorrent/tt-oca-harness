# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC entry 0 offset is not 8-byte aligned; the backup boots.

OCA constrains the entry offset, not the image length; the refusal is ``OCA_FAIL_PAYLOAD_TOC``.
Needs ``+esrc_noise_force``: two RSA-3072 modexps and AES decryptions.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_payload_image_offset_misaligned_test(
    sep_primary_toc_fail_base
):
    """Encrypted primary TOC entry 0 offset is 4 modulo 8 -> refused -> the backup boots."""

    toc_field = td.OFFSET_ALIGN
    encrypted = True
