# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP053-E: BL1 ``entry_point`` outside the image, so BL0 must not jump to it.

the BL1 placement check rejects ``entry_point >= length``, and
``validate_manifest_payload`` prints ``BL1_ENTRY_RANGE`` and returns
``MANIFEST_ERR_BL1_BAD_ADDR``. Both slots carry the
defect, so the ROM tries the primary, retries the backup and terminates.

THE STIMULUS IS THE BOUNDARY VALUE. ``entry_point`` is set to exactly ``length``
-- the smallest value the condition rejects -- rather than something comfortably
out of range. A ROM that had written ``>`` instead of ``>=`` would accept this and
jump one byte past the image; a larger entry point would be rejected by both the
correct and the incorrect comparison, and so could not tell them apart.

WHY THE SIZE ARM CANNOT ALSO FIRE. The BL1 placement check tests SRAM containment
first and only then the entry point, so this test must leave ``load_addr`` and
``length`` untouched -- which it does; the mutation writes one field. That is why
``BL1_ADDR_RANGE`` is in ``sibling_markers``: seeing it would mean the containment
arm returned 1 and the entry-point arm was never evaluated, even though the
run would still end on the same ``MANIFEST_ERR_BL1_BAD_ADDR`` code.
"""

from __future__ import annotations

import pyuvm
from env import sep_payload_mutate as pm
from rom_fw.sep_bl1_image_invalid_base import sep_bl1_image_invalid_base


@pyuvm.test()
class sep_bl1_entry_invalid_test(sep_bl1_image_invalid_base):
    """entry_point == length in both slots: rejected before the jump."""

    backup_defect_marker = "BL1_ENTRY_RANGE"
    expected_error = pm.MANIFEST_ERR_BL1_BAD_ADDR
    # The placement arm shares this test's error code, so only the marker
    # separates them. BL1_SIZE sits AHEAD of the entry-point comparison, so if it
    # fired the entry point was never reached.
    sibling_markers = ("BL1_ADDR_RANGE", "BL1_SIZE")

    def mutate_bl1(self, buf: bytearray, slot: str) -> None:
        length = pm.bl1_field(buf, slot, pm.E_LENGTH)
        before = pm.bl1_field(buf, slot, pm.E_ENTRY_POINT)
        assert before < length, (
            f"{slot} BL1 entry_point is already 0x{before:x} with length "
            f"0x{length:x}; the shipped image is supposed to be VALID here, so "
            f"this testcase would be asserting on a defect it did not plant"
        )
        written = pm.set_bl1_entry_point(buf, slot)
        assert written == length, f"expected the boundary value 0x{length:x}, wrote 0x{written:x}"
        self.logger.info(
            "CHK-STIMULUS-BL1-ENTRY: %s entry_point 0x%x -> 0x%x (== length, the "
            "smallest rejected value); %s",
            slot,
            before,
            written,
            pm.describe_bl1(buf, slot),
        )
