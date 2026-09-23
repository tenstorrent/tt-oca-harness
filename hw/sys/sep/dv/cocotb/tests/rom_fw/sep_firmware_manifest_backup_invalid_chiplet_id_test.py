# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup enables chiplet_id constraints it does not satisfy; the ROM halts.

A BAD_MAGIC identifier refuses the primary first, so both slots fail and the ROM
reports ERROR: INVALID_CHIPLET_ID.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_backup_usage_constraint_base

_SELECTOR_MASK = 0x28
_REJECT_INDEX = 3


@pyuvm.test()
class sep_firmware_manifest_backup_invalid_chiplet_id_test(
        sep_backup_usage_constraint_base):
    """Backup enables chiplet_id words 3 and 5 -> both slots refused -> halt."""

    defect_marker = fd.CHIPLET_MARKER
    defect_evidence = fd.device_id_required_markers("chiplet_id", _REJECT_INDEX)

    def plant(self, buf: bytearray, slot: str) -> None:
        index = fd.plant_device_id_defect(buf, slot, "chiplet_id", _SELECTOR_MASK)
        assert index == _REJECT_INDEX, (
            f"selector mask 0x{_SELECTOR_MASK:02x} makes word {index} the lowest "
            f"enabled one, but this testcase asserts {_REJECT_INDEX}"
        )
        self.logger.info(
            "CHK-STIMULUS-CHIPLET-ID: %s selector_bits[0..7] = 0x%02x, so the ROM "
            "must read chiplet_id words %s and refuse on word %d",
            slot, _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)], index,
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "chiplet_id",
                                     _REJECT_INDEX)
