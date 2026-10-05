# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BL1 length zero in both slots must be refused before the copy, as a TOC violation.

A zero-length TOC entry authenticates nothing and cannot be launched, so the validation
library refuses each slot with ``OCA_FAIL_PAYLOAD_TOC``. The primary fails, the backup
fails the same way, and the boot terminates without a BL1 copy or jump. The exact
``MANIFEST_ERR=`` code must appear once per slot; no console token is dedicated to it.

``rom_bl1_check()`` (``rom_handoff.c``) also refuses a zero length (``BL1_SIZE``), but the
library gates first, so ``BL1_SIZE`` is forbidden. ``NO_BL1_IMAGE`` is forbidden too: a
mutation that lost the entry type would also end the boot.

Only the zero-length class is covered. A BL1 larger than IRAM or than the spec maximum
needs ``length > 0x40000``, which needs a payload above 128 KiB and is not exercised.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_bl1_image_invalid_base import sep_bl1_image_invalid_base

MANIFEST_ERR_PAYLOAD_TOC = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")


@pyuvm.test()
class sep_bl1_size_invalid_test(sep_bl1_image_invalid_base):
    """BL1 length zero in both slots: refused as a structural TOC violation."""

    expected_error = MANIFEST_ERR_PAYLOAD_TOC
    backup_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_PAYLOAD_TOC:08x}"
    # Every arm of the ROM's own BL1 check. All three sit downstream of payload
    # validation, so any of them appearing would mean the structural rule did not
    # reject the slot and the ROM caught this at hand-off instead.
    sibling_markers = ("BL1_ADDR_RANGE", "BL1_ENTRY_RANGE", "BL1_SIZE")

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
        # The entry must still be a SEP BL1 entry, so length is the only defect;
        # find_image() locates it by type and raises on a damaged type.
        # entry_type, not bl1_field: the type is a 16-byte string, and bl1_field
        # reads u64 fields.
        got_type = pm.entry_type(buf, pm.find_image(buf, slot))
        assert got_type == pm.IMAGE_TYPE_SEP_BL1, (
            f"{slot} BL1 entry type is {got_type!r}, expected {pm.IMAGE_TYPE_SEP_BL1!r}"
        )
        self.logger.info(
            "CHK-STIMULUS-BL1-SIZE: %s BL1 length %d -> 0, type and load_addr untouched; %s",
            slot,
            was,
            pm.describe_bl1(buf, slot),
        )
