# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC declares 257 images, more than the payload holds; the ROM halts.

The count-fit rule refuses it with ``OCA_FAIL_PAYLOAD_TOC`` before the image cap is checked.
Needs ``+esrc_noise_force``: an RSA-3072 modexp.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_invalid_payload_image_count_test(sep_backup_toc_fail_base):
    """Plaintext backup TOC image_count is 257 -> both slots refused -> halt."""

    toc_field = td.IMAGE_COUNT
    encrypted = False
