# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup selects chiplet_id bytes that differ from SEP_CHIPLET_ID; the ROM halts.

The primary is refused as ``OCA_FAIL_MAGIC``, so the terminal ``OCA_FAIL_CHIPLET_ID``
identifies the backup.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    MANIFEST_ERR_CHIPLET_ID,
    sep_backup_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_backup_invalid_chiplet_id_test(sep_backup_usage_constraint_base):
    """Backup chiplet_id bytes 3 and 5 mismatch the fuse -> refused."""

    expected_error = MANIFEST_ERR_CHIPLET_ID
    backup_defect_marker = err_marker(MANIFEST_ERR_CHIPLET_ID)

    def plant(self, buf: bytearray, slot: str) -> None:
        self.plant_identity(buf, slot, "chiplet", mismatch=(3, 5))
