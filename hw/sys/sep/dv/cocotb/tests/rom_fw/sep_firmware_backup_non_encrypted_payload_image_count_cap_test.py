# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC declares one image past the ROM's cap; the ROM halts.

The TOC fits the payload, so the build-time ``OCA_TOC_MAX_IMAGES`` cap refuses it with
``OCA_FAIL_PAYLOAD_TOO_MANY_IMAGES``. Needs ``+esrc_noise_force``: an RSA-3072 modexp.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_image_count_cap_test(sep_backup_toc_fail_base):
    """Plaintext backup TOC image_count is cap + 1 and fits -> both slots refused -> halt."""

    toc_field = td.IMAGE_COUNT_CAP
    encrypted = False
