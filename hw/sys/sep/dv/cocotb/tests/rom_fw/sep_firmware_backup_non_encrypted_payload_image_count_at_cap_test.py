# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC declares exactly the ROM's cap of images; the cap lets it through.

The cap is the build-time ``OCA_TOC_MAX_IMAGES``; zero-length entries 1.. must fail with
``OCA_FAIL_PAYLOAD_TOC``, never ``OCA_FAIL_PAYLOAD_TOO_MANY_IMAGES``. Needs ``+esrc_noise_force``.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_image_count_at_cap_test(sep_backup_toc_fail_base):
    """Plaintext backup TOC image_count equals the cap -> PAYLOAD_TOC, not TOO_MANY -> halt."""

    toc_field = td.IMAGE_COUNT_AT_CAP
    encrypted = False
