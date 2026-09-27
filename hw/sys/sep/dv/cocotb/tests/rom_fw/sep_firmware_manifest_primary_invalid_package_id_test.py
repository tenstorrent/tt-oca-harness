# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary enables package_id constraints it does not satisfy; the backup boots.

Mask 0x14 (selector_bits[8..15]) makes package_id word 2 the first mismatch, so the
ROM's PID_IDX= echo is checked. The fuse-map value is a model property, not asserted.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_primary_usage_constraint_base

_SELECTOR_MASK = 0x14
_REJECT_INDEX = 2


@pyuvm.test()
class sep_firmware_manifest_primary_invalid_package_id_test(sep_primary_usage_constraint_base):
    """Primary enables package_id words 2 and 4 -> refused -> the backup boots."""

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
            "must read package_id words %s and refuse on word %d; every enabled "
            "word carries the shipped 0x%08x",
            slot,
            _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)],
            index,
            0xA5A5A5A5,
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "package_id", _REJECT_INDEX)
