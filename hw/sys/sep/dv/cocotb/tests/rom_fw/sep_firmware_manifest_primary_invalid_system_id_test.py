# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary selects one system_id byte that differs from SEP_SYS_ID; the backup boots.

``oca_check_identity`` refuses the primary with ``OCA_FAIL_SYSTEM_ID`` before key
selection. The check prints nothing of its own, so the code is the evidence.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    MANIFEST_ERR_SYSTEM_ID,
    sep_primary_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_primary_invalid_system_id_test(sep_primary_usage_constraint_base):
    """Primary system_id byte 7 mismatches the fuse -> refused -> the backup boots."""

    primary_expected_error = MANIFEST_ERR_SYSTEM_ID
    primary_defect_marker = err_marker(MANIFEST_ERR_SYSTEM_ID)

    def plant(self, buf: bytearray, slot: str) -> None:
        self.plant_identity(buf, slot, "system", mismatch=(7,))
