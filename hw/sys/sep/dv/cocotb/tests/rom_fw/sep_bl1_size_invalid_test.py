# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP053-S: BL1 image size out of range, so BL0 must reject before the copy.

The SEP BL1 entry's ``length`` is set to zero in BOTH manifest slots. The ROM
rejects each slot -- ``IMAGE_LEN_ZERO idx=0`` then
``MANIFEST_ERR_IMAGE_OOB`` -- so the primary fails, the backup is retried, it
fails the same way, and the boot terminates without BL1 ever being copied into
SRAM or entered.

WHICH OF THE PROCEDURE'S THREE SIZE CLASSES THIS COVERS, AND WHICH IT DOES NOT.
TP053-S names three: zero, larger than IRAM, and larger than the spec's maximum
BL1 size. **Only the zero class is exercised here**, and the omission is a
property of the ROM's check order rather than a choice of convenience:

  * *larger than IRAM* would have to reach ``check_bl1_image``'s containment arm
    (``BL1_ADDR_RANGE``), which with the shipped
    ``load_addr`` of 0xC0000000 needs ``length > 0x40000``. But
     rejects ``offset + length > payload_length`` first, so
    the payload would have to grow past 128 KiB -- roughly 80 ms of extra
    simulated SPI transfer per slot at this testbench's rate, on both slots.
    ``sep_oca_payload.set_bl1_zero_length``'s docstring records the analysis.
  * *larger than the spec maximum* is checked at ``rom_handoff.c``
    (``BL1_SIZE`` / ``MANIFEST_ERR_BL1_TOO_LARGE``), which is downstream of
    manifest validation.  says as much in its own
    comment: by the time handoff runs, the slot has already been accepted. Both
    of that gate's arms are therefore already rejected upstream, and it cannot be
    reached from a manifest at all.

So this testcase establishes the procedure's central claim -- an out-of-range BL1
size is rejected before any BL1 copy or jump -- for one of the three size classes.
The other two are NOT covered by a pass here.

ATTRIBUTION. The marker carries the entry index, and this payload's TOC holds
exactly one image which is the BL1, so ``IMAGE_LEN_ZERO idx=0`` names the entry
that was mutated rather than some other image. ``NO_BL1_IMAGE`` is forbidden
because a mutation that lost the entry's type instead of its length would also
end the boot, and would otherwise look the same from the outside.
"""

from __future__ import annotations

import pyuvm
from env import sep_oca_mutate as mm
from env import sep_oca_payload as pm
from rom_fw.sep_bl1_image_invalid_base import sep_bl1_image_invalid_base

MANIFEST_ERR_BL1_TOO_LARGE = mm.rom_boot_err("OCA_BOOT_ERR_BL1_TOO_LARGE")


@pyuvm.test()
class sep_bl1_size_invalid_test(sep_bl1_image_invalid_base):
    """BL1 length zero in both slots: rejected before the copy into SRAM."""

    backup_defect_marker = "BL1_SIZE"
    expected_error = MANIFEST_ERR_BL1_TOO_LARGE
    # The other two arms of the same check. Each ends the boot the same way, and
    # BL1_ENTRY_RANGE in particular is what a zero length reports as if the length
    # arm ran second -- so its absence is what pins the attribution.
    sibling_markers = ("BL1_ADDR_RANGE", "BL1_ENTRY_RANGE")

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
        # The entry must still be a SEP BL1 entry: find_image() locates it by type,
        # so a mutation that damaged the type would raise there rather than here,
        # but stating it makes the "size is the only defect" claim explicit.
        assert pm.bl1_field(buf, slot, pm.E_TYPE) == pm.IMAGE_TYPE_SEP_BL1
        self.logger.info(
            "CHK-STIMULUS-BL1-SIZE: %s BL1 length %d -> 0, type and load_addr untouched; %s",
            slot,
            was,
            pm.describe_bl1(buf, slot),
        )
