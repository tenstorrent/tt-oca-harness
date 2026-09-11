# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup enables package_id constraints it does not satisfy; the ROM halts.

The mirror of ``sep_firmware_manifest_primary_invalid_package_id_test``, and the
package_id counterpart of
``sep_firmware_manifest_backup_invalid_chiplet_id_test``. The primary is refused
by the shared identifier trigger, the backup is refused on
``selector_bits[8..15]`` with ``PACKAGE_ID_MISMATCH`` and
``MANIFEST_ERR_LC_USAGE_CONSTRAINT``, and with both slots refused the ROM halts
(``bootrom/prod/src/manifest_load.c``, ``bootrom/prod/src/rom_main.c``). The
reference expects the terminal ``ERROR: INVALID_PACKAGE_ID``.

The failover-trigger adaptation is the one described in the chiplet_id sibling.
payload TOC version; here the TOC is validated inside the slot attempt and the
manifest's secure-boot flag is ignored in PROD, so neither half reproduces and the
deterministic BAD_MAGIC trigger is used instead.

**HOW THIS IS TOLD APART FROM THE OTHER TWO BACKUP-SIDE ARMS.** All three end at
the same error code, the same status word and the same halt, so this member
requires ``PACKAGE_ID_MISMATCH``, forbids ``CHIPLET_ID_MISMATCH`` and
``LC_USAGE_CONSTRAINT_FAIL``, and asserts an index (word 2) that the chiplet
sibling's mask cannot produce.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_backup_usage_constraint_base

_SELECTOR_MASK = 0x14
_REJECT_INDEX = 2


@pyuvm.test()
class sep_firmware_manifest_backup_invalid_package_id_test(
        sep_backup_usage_constraint_base):
    """Backup enables package_id words 2 and 4 -> both slots refused -> halt."""

    defect_marker = fd.PACKAGE_MARKER
    defect_evidence = fd.device_id_required_markers("package_id", _REJECT_INDEX)

    def plant(self, buf: bytearray, slot: str) -> None:
        index = fd.plant_device_id_defect(buf, slot, "package_id", _SELECTOR_MASK)
        assert index == _REJECT_INDEX, (
            f"selector mask 0x{_SELECTOR_MASK:02x} makes word {index} the lowest "
            f"enabled one, but this testcase asserts {_REJECT_INDEX}"
        )
        self.logger.info(
            "CHK-STIMULUS-PACKAGE-ID: %s selector_bits[8..15] = 0x%02x, so the ROM "
            "must read package_id words %s and refuse on word %d",
            slot, _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)], index,
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "package_id",
                                     _REJECT_INDEX)
