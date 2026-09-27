# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC places image 0 inside the TOC region; the ROM halts.

Image 0 offset 240 lies inside the 248-byte TOC region and is refused with
``IMAGE_ORDER_BAD idx=0x00000000``; the primary is refused as BAD_MAGIC.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_toc_bound_fail_base import sep_backup_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_image_exceeds_bound_test(
    sep_backup_toc_bound_fail_base
):
    """Plaintext backup TOC starts image 0 inside the TOC region -> halt."""

    bound_defect = tbd.BOUND
    encrypted = False
