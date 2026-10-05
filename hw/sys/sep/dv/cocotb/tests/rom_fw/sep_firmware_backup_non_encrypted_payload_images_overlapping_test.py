# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC is stored in descending order and entry 1 overlaps entry 2; the ROM halts.

Any entry order is legal, so the overlap is the only broken rule (``OCA_FAIL_PAYLOAD_TOC``).
Needs ``+esrc_noise_force``: an RSA-3072 modexp.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_payload_images_overlapping_test(sep_backup_toc_fail_base):
    """Plaintext backup TOC entry 1 overlaps entry 2 -> both slots refused -> halt."""

    toc_field = td.OVERLAP
    encrypted = False
