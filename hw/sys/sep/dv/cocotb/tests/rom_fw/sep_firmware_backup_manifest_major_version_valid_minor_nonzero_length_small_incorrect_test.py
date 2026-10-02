# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.1 with manifest_length one word below the body size; the ROM halts."""

from __future__ import annotations

import pyuvm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_length_fail_base import sep_backup_manifest_length_fail_base


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_small_incorrect_test(
    sep_backup_manifest_length_fail_base
):
    """Backup is v1.1 with length body-4 -> both slots refused -> the ROM halts."""

    backup_minor = 1
    backup_length = fd.assert_consumer_body_size() - 4
