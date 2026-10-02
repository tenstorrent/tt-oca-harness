# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary selects package_id bytes that differ from SEP_SIP_ID; the backup boots.

``oca_check_identity`` refuses the primary with ``OCA_FAIL_PACKAGE_ID`` before key
selection. The check prints nothing of its own, so the code is the evidence.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    MANIFEST_ERR_PACKAGE_ID,
    sep_primary_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_primary_invalid_package_id_test(sep_primary_usage_constraint_base):
    """Primary package_id bytes 2 and 4 mismatch the fuse -> refused."""

    primary_expected_error = MANIFEST_ERR_PACKAGE_ID
    primary_defect_marker = err_marker(MANIFEST_ERR_PACKAGE_ID)

    def plant(self, buf: bytearray, slot: str) -> None:
        self.plant_identity(buf, slot, "package", mismatch=(2, 4))
