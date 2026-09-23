# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Test that the ROM rejects a BL1 entry_point equal to the image length in both slots.

entry_point == length is the smallest rejected value, so a ROM that tests `>` instead of `>=` fails.
The ROM must refuse both slots with MANIFEST_ERR_BL1_BAD_ADDR and halt before any jump.
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
    # Same error code or earlier checks on the same path; only these markers tell them apart.
    sibling_markers = ("BL1_ADDR_RANGE", "IMAGE_LEN_ZERO", "IMAGE_LEN_ALIGN")

    def mutate_bl1(self, buf: bytearray, slot: str) -> None:
        length = pm.bl1_field(buf, slot, pm.E_LENGTH)
        before = pm.bl1_field(buf, slot, pm.E_ENTRY_POINT)
        assert before < length, (
            f"{slot} BL1 entry_point is already 0x{before:x} with length "
            f"0x{length:x}; the shipped image is supposed to be VALID here, so "
            f"this testcase would be asserting on a defect it did not plant"
        )
        written = pm.set_bl1_entry_point(buf, slot)
        assert written == length, (
            f"expected the boundary value 0x{length:x}, wrote 0x{written:x}"
        )
        self.logger.info(
            "CHK-STIMULUS-BL1-ENTRY: %s entry_point 0x%x -> 0x%x (== length, the "
            "smallest rejected value); %s",
            slot, before, written, pm.describe_bl1(buf, slot),
        )
