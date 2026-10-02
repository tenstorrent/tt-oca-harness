# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary does not permit the live lifecycle; the backup boots.

The primary permits every chiplet lifecycle token except PROD, the preload's live state,
so ``oca_lifecycle_check`` refuses it with ``OCA_FAIL_LIFECYCLE`` before key selection.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    LC_ALLOWED_WITHOUT_LIVE,
    MANIFEST_ERR_LIFECYCLE,
    sep_primary_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_primary_lc_state_failure_test(sep_primary_usage_constraint_base):
    """Primary permits every lifecycle but PROD on a PROD part -> refused -> backup boots."""

    primary_expected_error = MANIFEST_ERR_LIFECYCLE
    primary_defect_marker = err_marker(MANIFEST_ERR_LIFECYCLE)

    def plant(self, buf: bytearray, slot: str) -> None:
        self.plant_lifecycle(buf, slot, LC_ALLOWED_WITHOUT_LIVE, "chiplet")
