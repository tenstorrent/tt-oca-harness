# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary selects a package lifecycle constraint the SEP cannot report; the backup boots.

The SEP reports a chiplet lifecycle only, so ``oca_lifecycle_check`` refuses the slot
with ``OCA_FAIL_CALLBACK_UNAVAILABLE``; the bitmap permits every token, PROD included.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    LIVE_LC_BIT,
    MANIFEST_ERR_CALLBACK_UNAVAILABLE,
    sep_primary_usage_constraint_base,
)

_ALLOWED = mm.LIFECYCLE_STATES_VALID_MASK


@pyuvm.test()
class sep_firmware_manifest_primary_unsupported_lifecycle_level_test(
    sep_primary_usage_constraint_base
):
    """Primary constrains the package lifecycle -> refused as unavailable -> backup boots."""

    primary_expected_error = MANIFEST_ERR_CALLBACK_UNAVAILABLE
    primary_defect_marker = err_marker(MANIFEST_ERR_CALLBACK_UNAVAILABLE)

    def plant(self, buf: bytearray, slot: str) -> None:
        assert _ALLOWED & (1 << LIVE_LC_BIT), (
            f"allowed 0x{_ALLOWED:x} excludes the live PROD token, so a refusal could "
            f"come from the bitmap instead of the unreportable level"
        )
        self.plant_lifecycle(buf, slot, _ALLOWED, "package")
