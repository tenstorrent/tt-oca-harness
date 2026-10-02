# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup selects package_id bytes that differ from SEP_SIP_ID; the ROM halts.

The primary is refused as ``OCA_FAIL_MAGIC``, so the terminal ``OCA_FAIL_PACKAGE_ID``
identifies the backup.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    MANIFEST_ERR_PACKAGE_ID,
    sep_backup_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_backup_invalid_package_id_test(sep_backup_usage_constraint_base):
    """Backup package_id bytes 2 and 4 mismatch the fuse -> refused."""

    expected_error = MANIFEST_ERR_PACKAGE_ID
    backup_defect_marker = err_marker(MANIFEST_ERR_PACKAGE_ID)

    def plant(self, buf: bytearray, slot: str) -> None:
        self.plant_identity(buf, slot, "package", mismatch=(2, 4))
