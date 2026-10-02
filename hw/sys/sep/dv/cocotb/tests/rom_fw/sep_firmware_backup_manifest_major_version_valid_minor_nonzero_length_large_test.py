# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.1 with the PQC body size as manifest_length; the ROM halts.

The length is legal for the other variant only: the rule compares against the body
size the magic selects, not against any known body size.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_length_fail_base import sep_backup_manifest_length_fail_base


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_large_test(
    sep_backup_manifest_length_fail_base
):
    """Backup is OCAC v1.1 with length 36864 -> both slots refused -> the ROM halts."""

    backup_minor = 1
    backup_length = mm.K.OCA_PQC_BODY_SIZE
