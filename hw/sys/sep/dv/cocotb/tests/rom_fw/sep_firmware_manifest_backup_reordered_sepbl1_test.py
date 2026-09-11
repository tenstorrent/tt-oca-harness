# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The BACKUP's SEP_BL1 is not its first TOC image; the backup boots anyway.

The mirror of ``sep_firmware_manifest_primary_reordered_sepbl1_test``, and the
reference treats it as a distinct scenario rather than a repeat: the primary is
refused first, and the position-independent BL1 lookup then has to work on the slot
the ROM fell over TO. That is a different code path from the primary case --
``rom_manifest_boot`` clears SEP SRAM and re-initialises the flash controller
between the two attempts (``bootrom/prod/src/manifest_load.c``), so the backup's
TOC is parsed out of freshly DMA'd memory.

THE FAILOVER TRIGGER: the primary's
``usage_constraints.selector_bits`` package_id half, graded
``WARNING: INVALID_PACKAGE_ID`` there and ``PACKAGE_ID_MISMATCH`` /
``MANIFEST_ERR_LC_USAGE_CONSTRAINT`` here. The shipped image already carries
``0xa5a5a5a5`` in every package_id word with the selectors clear, so the selector
bit is the whole stimulus -- see ``sep_manifest_field_defect``. The mask is
deliberately neither ``sep_firmware_manifest_primary_invalid_package_id_test``'s
(word 2) nor ``sep_firmware_manifest_backup_missing_sepbl1_test``'s (word 1), so
each of the three asserts a ``PID_IDX=`` the other two's runs cannot produce.

THE STIMULUS IS AN INSERT, NOT A PERMUTATION, for the reason given in full in the
primary-side sibling: this image declares exactly one payload image, so the second
one has to be created for "SEPBL1 is not first" to mean anything.

WHAT SEPARATES A PASSING RUN FROM ITS NEAREST NEIGHBOUR. This testcase and
``sep_firmware_manifest_primary_invalid_package_id_test`` share a primary verdict
and both end in a backup boot, so the failover alone is worth nothing here. Three
things differ, and all three are asserted: the accepted slot prints
``IMAGES=0x00000002`` where every one-image payload prints ``IMAGES=0x00000001``;
``COPY_SRC=`` names the RELOCATED BL1 address, which the ROM can only print by
reading TOC entry 1's ``offset`` (``rom_handoff.c``); and the package_id word the
primary is refused on is a different one.
"""

from __future__ import annotations

import pyuvm

from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_primary_usage_constraint_base

# Within the 1, 0xff range, and not the mask used by
# sep_firmware_manifest_primary_invalid_package_id_test (0x14, word 2) or by
# sep_firmware_manifest_backup_missing_sepbl1_test (0x42, word 1): words 4 and 7,
# so the ROM refuses on word 4.
_SELECTOR_MASK = 0x90
_REJECT_INDEX = 4

_TWO_IMAGES = "IMAGES=0x00000002"


@pyuvm.test()
class sep_firmware_manifest_backup_reordered_sepbl1_test(
        sep_primary_usage_constraint_base):
    """Primary refused on package_id; the backup's BL1 sits at TOC index 1 and boots."""

    defect_marker = fd.PACKAGE_MARKER
    defect_evidence = fd.device_id_required_markers("package_id", _REJECT_INDEX)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The two-image TOC is the accepted slot's, so it belongs with the base's
        # own recovery markers rather than in a separate check.
        self.required_markers += (_TWO_IMAGES,)
        # None of the TOC verdicts a mis-built insert would produce may appear, and
        # a position-dependent ROM would print NO_BL1_IMAGE here.
        self.forbidden_markers += (
            "NO_BL1_IMAGE", "IMAGE_ORDER_BAD", "IMAGE_LEN_ZERO", "IMAGE_LEN_ALIGN",
            "IMAGE_HASH_MISMATCH", "TOC_REGION_OOB=", "TOC_PLEN_MISMATCH=",
            "BAD_IMAGE_TYPE", "BL1_ADDR_RANGE", "BL1_ENTRY_RANGE",
        )

    def plant(self, buf: bytearray, slot: str) -> None:
        index = fd.plant_device_id_defect(buf, slot, "package_id", _SELECTOR_MASK)
        assert index == _REJECT_INDEX, (
            f"selector mask 0x{_SELECTOR_MASK:02x} makes word {index} the lowest "
            f"enabled one, but this testcase asserts {_REJECT_INDEX}"
        )
        self.logger.info(
            "CHK-STIMULUS-TRIGGER: %s selector_bits[8..15] = 0x%02x, so the ROM "
            "must read package_id words %s and refuse on word %d",
            slot, _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)], index,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        self.logger.info("CHK-STIMULUS-BL1-BEFORE: %s", pm.describe_bl1(buf, "backup"))
        before = pm.bl1_sram_source(buf, "backup")
        geo = pm.insert_leading_image(buf, "backup")
        self._geometry = geo
        self._copy_src = pm.bl1_sram_source(buf, "backup")
        assert self._copy_src != before, (
            "the BL1 body did not move, so COPY_SRC= would be the value an "
            "unmodified backup prints and could not discriminate this run"
        )
        entries = pm.toc_entries(buf, "backup")
        assert len(entries) == 2, f"backup TOC has {len(entries)} images, expected 2"
        assert pm._u64(buf, entries[1] + pm.E_TYPE) == pm.IMAGE_TYPE_SEP_BL1, (
            "SEP_BL1 is not backup TOC entry 1, so the payload does not exercise "
            "position independence"
        )
        self.logger.info(
            "CHK-STIMULUS-REORDER: backup TOC is now [0x%x @%d len %d, SEP_BL1 @%d "
            "len %d]; TOC region %d bytes, payload_hashed_length %d, "
            "payload_length unchanged. BL1 body moved %d -> %d, so COPY_SRC must "
            "read 0x%08x instead of 0x%08x",
            geo["lead_type"], geo["lead_offset"], geo["lead_length"],
            geo["bl1_offset_after"], geo["bl1_length"], geo["toc_region"],
            geo["payload_hashed_length"], geo["bl1_offset_before"],
            geo["bl1_offset_after"], self._copy_src, before,
        )
        self.logger.info("CHK-STIMULUS-BL1-AFTER:  %s", pm.describe_bl1(buf, "backup"))

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "package_id",
                                     _REJECT_INDEX)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        # CHK-POSITION-INDEPENDENT: the recovered boot copied BL1 from the address
        # the BACKUP's TOC entry 1 names, and did so after the backup was read. The
        # base already proved the failover; this is what proves the recovered slot
        # is the reordered one rather than an untouched backup.
        want = f"COPY_SRC=0x{self._copy_src:08x}"
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_images = fd.first_index(console, _TWO_IMAGES)
        i_copy = fd.first_index(console, want)
        assert i_copy >= 0, (
            f"ROM never printed {want}. The backup's BL1 body sits at payload "
            f"offset {self._geometry['bl1_offset_after']} and TOC entry 1 names it, "
            f"so a ROM that scanned the TOC by type must copy from there. Console: "
            f"{console}"
        )
        assert fd.count(console, want) == 1, (
            f"{want} appeared more than once; only one slot is handed off. "
            f"Console: {console}"
        )
        assert i_bsrc < i_images < i_copy, (
            f"backup read@{i_bsrc} -> {_TWO_IMAGES}@{i_images} -> {want}@{i_copy} "
            f"is not the order the ROM emits; the two-image payload is not the "
            f"accepted backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-BL1-BY-TYPE: backup read@%d -> %s@%d -> %s@%d -- the recovered "
            "slot declared two images and the ROM copied BL1 from TOC entry 1's "
            "offset, so it located BL1 by type on the failover path too",
            i_bsrc, _TWO_IMAGES, i_images, want, i_copy,
        )
