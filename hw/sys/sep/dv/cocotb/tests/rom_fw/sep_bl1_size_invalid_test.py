# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP053-S: BL1 image size out of range, so the boot must reject before the copy.

The SEP BL1 entry's ``length`` is set to zero in BOTH manifest slots. A
zero-length TOC entry is a structural violation, so the validation library
refuses each slot with ``OCA_FAIL_PAYLOAD_TOC`` while checking the payload: the
primary fails, the backup is retried, it fails the same way, and the boot
terminates without BL1 ever being copied or entered.

WHERE THE REJECTION COMES FROM, AND WHY THAT IS THE POINT. A zero-length entry
declares an image with no content. Its ``hash`` is the digest of the empty
string, so it authenticates nothing; ``entry_point < length`` can never hold, so
it can never be legally launched; and it satisfies both the extent bound and the
overlap test trivially, so no other structural rule rejects it. A consumer that
selected an image by type and then loaded ``length`` bytes would copy nothing and
hand control to whatever already occupied ``load_addr``. The library rejects it so
no consumer has to carry that guard itself, and this testcase is what holds it to
that.

THE ROM'S OWN LENGTH ARM IS DELIBERATELY NOT WHAT THIS ASSERTS. ``rom_bl1_check``
also refuses a zero length (``BL1_SIZE``), and keeps doing so, because the ROM
must not depend on which library version it links. But the library gates first,
so that arm is unreachable from a manifest -- and ``BL1_SIZE`` is therefore
FORBIDDEN below. Its absence is the positive evidence that the structural rule
ran ahead of hand-off rather than the ROM catching this late.

WHICH OF THE PROCEDURE'S THREE SIZE CLASSES THIS COVERS. TP053-S names three:
zero, larger than IRAM, and larger than the spec's maximum BL1 size. **Only the
zero class is exercised here.** The other two would have to reach the ROM's
placement arm, which needs ``length > 0x40000`` against the shipped
``load_addr``; the library rejects ``offset + length > payload_length`` first, so
the payload would have to grow past 128 KiB -- roughly 80 ms of extra simulated
SPI transfer per slot, on both slots. ``sep_payload_mutate.set_bl1_zero_length``'s
docstring records the analysis. A pass here does not cover those two.

ATTRIBUTION. The rejection carries no dedicated console token, so the exact
``MANIFEST_ERR=`` code is the discriminator, and it must appear once per slot.
``NO_BL1_IMAGE`` is forbidden because a mutation that lost the entry's type
instead of its length would also end the boot and would otherwise look the same
from the outside.
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
        # The entry must still be a SEP BL1 entry: find_image() locates it by type,
        # so a mutation that damaged the type would raise there rather than here,
        # but stating it makes the "size is the only defect" claim explicit.
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
