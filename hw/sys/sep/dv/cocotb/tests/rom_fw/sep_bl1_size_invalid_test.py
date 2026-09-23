# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Test that the ROM rejects a zero BL1 length in both slots before it copies BL1."""

from __future__ import annotations

import pyuvm

from env import sep_payload_mutate as pm
from rom_fw.sep_bl1_image_invalid_base import sep_bl1_image_invalid_base

MANIFEST_ERR_IMAGE_OOB = 0x0003_000E


@pyuvm.test()
class sep_bl1_size_invalid_test(sep_bl1_image_invalid_base):
    """BL1 length zero in both slots: rejected before the copy into SRAM."""

    backup_defect_marker = "IMAGE_LEN_ZERO"
    expected_error = MANIFEST_ERR_IMAGE_OOB
    # Other rejections on the same path that would end the boot in a similar way.
    sibling_markers = ("IMAGE_LEN_ALIGN", "BL1_ADDR_RANGE", "BL1_ENTRY_RANGE")

    def mutate_bl1(self, buf: bytearray, slot: str) -> None:
        before = pm.bl1_field(buf, slot, pm.E_LENGTH)
        assert before != 0, (
            f"{slot} BL1 length is already 0; the shipped image is supposed to be "
            f"VALID here, so this testcase would be asserting on a defect it did "
            f"not plant"
        )
        was = pm.set_bl1_zero_length(buf, slot)
        assert was == before
        assert pm.bl1_field(buf, slot, pm.E_LENGTH) == 0
        assert pm.bl1_field(buf, slot, pm.E_TYPE) == pm.IMAGE_TYPE_SEP_BL1
        self.logger.info(
            "CHK-STIMULUS-BL1-SIZE: %s BL1 length %d -> 0, type and load_addr "
            "untouched; %s", slot, was, pm.describe_bl1(buf, slot),
        )
