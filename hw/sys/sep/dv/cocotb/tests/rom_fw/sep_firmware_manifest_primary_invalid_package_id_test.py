# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary enables package_id constraints it does not satisfy; the backup boots.

``selector_bits[8..15]`` are the ``usage_constraints.package_id`` selectors, read
as ``sel >> 8`` and indexed 0..7 into the array, so the ROM reads the SMC fuse map
at ``SMC_FUSE_MAP_PACKAGE_ID_OFFSET + i*4`` and refuses the slot on the first
disagreement with ``PACKAGE_ID_MISMATCH`` and
``MANIFEST_ERR_LC_USAGE_CONSTRAINT`` (``bootrom/prod/src/manifest_load.c``). The
reference expects that verdict on the primary and a completed boot from the
backup.

The stimulus, the fixed-mask reasoning and the limits on what the fuse side may
claim are the same as for the chiplet_id sibling; see
``sep_firmware_manifest_primary_invalid_chiplet_id_test``, with the mask shifted
left by 8 to address the package_id half.

**HOW THIS IS TOLD APART FROM ITS CHIPLET_ID SIBLING.** Both arms return
``MANIFEST_ERR_LC_USAGE_CONSTRAINT``, both end in a backup boot, and the status
word is identical, so the error code cannot separate them. Two things do, in both
directions: ``PACKAGE_ID_MISMATCH`` is required here and forbidden there while
``CHIPLET_ID_MISMATCH`` is forbidden here and required there, and the mask is a
DIFFERENT one -- 0x14 (words 2 and 4) against the sibling's 0x28 (words 3 and 5)
-- so each testcase asserts an index the other's run cannot produce.

MARKER SUBSTITUTION. ``SEP_MSG_INVALID_PACKAGE_ID`` is defined in
``bootrom/prod/include/status_values.h`` and emitted nowhere, so the debug
console token is the only per-reason evidence available.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_primary_usage_constraint_base

# Within the 1, 0xff range, and deliberately not the
# chiplet sibling's mask: the two indices must be mutually exclusive.
_SELECTOR_MASK = 0x14
_REJECT_INDEX = 2


@pyuvm.test()
class sep_firmware_manifest_primary_invalid_package_id_test(
        sep_primary_usage_constraint_base):
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
            slot, _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)], index,
            0xA5A5A5A5,
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "package_id",
                                     _REJECT_INDEX)
