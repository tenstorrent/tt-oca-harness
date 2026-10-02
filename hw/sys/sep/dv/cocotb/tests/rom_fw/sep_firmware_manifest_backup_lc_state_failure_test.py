# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup does not permit the live lifecycle; the ROM halts.

The backup permits every chiplet lifecycle token except PROD, the preload's live state,
so it fails with ``OCA_FAIL_LIFECYCLE``; the primary fails as ``OCA_FAIL_MAGIC``.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    LC_ALLOWED_WITHOUT_LIVE,
    MANIFEST_ERR_LIFECYCLE,
    sep_backup_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_backup_lc_state_failure_test(sep_backup_usage_constraint_base):
    """Backup permits every lifecycle but PROD on a PROD part -> both refused -> halt."""

    expected_error = MANIFEST_ERR_LIFECYCLE
    backup_defect_marker = err_marker(MANIFEST_ERR_LIFECYCLE)

    def plant(self, buf: bytearray, slot: str) -> None:
        self.plant_lifecycle(buf, slot, LC_ALLOWED_WITHOUT_LIVE, "chiplet")
