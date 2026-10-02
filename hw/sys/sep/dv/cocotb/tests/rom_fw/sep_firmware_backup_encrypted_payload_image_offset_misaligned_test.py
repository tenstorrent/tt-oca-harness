# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC entry 0 offset is not 8-byte aligned; the ROM halts.

OCA constrains the entry offset, not the image length, so the offset moves back 4 bytes.
Needs ``+esrc_noise_force``: an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_payload_image_offset_misaligned_test(sep_backup_toc_fail_base):
    """Encrypted backup TOC entry 0 offset is 4 modulo 8 -> both slots refused -> halt."""

    toc_field = td.OFFSET_ALIGN
    encrypted = True
