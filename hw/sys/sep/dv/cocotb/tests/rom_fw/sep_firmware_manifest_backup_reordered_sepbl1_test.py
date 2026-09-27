# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The backup's SEP_BL1 is not its first TOC image; the backup still boots.

The primary is refused on a package_id selector; the ROM must find BL1 by type in the
backup's two-image TOC, so IMAGES=0x00000002 and the relocated COPY_SRC= must appear.
"""

from __future__ import annotations

import pyuvm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_primary_usage_constraint_base

_SELECTOR_MASK = 0x90
_REJECT_INDEX = 4

_TWO_IMAGES = "IMAGES=0x00000002"


@pyuvm.test()
class sep_firmware_manifest_backup_reordered_sepbl1_test(sep_primary_usage_constraint_base):
    """Primary refused on package_id; the backup's BL1 sits at TOC index 1 and boots."""

    defect_marker = fd.PACKAGE_MARKER
    defect_evidence = fd.device_id_required_markers("package_id", _REJECT_INDEX)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.required_markers += (_TWO_IMAGES,)
        self.forbidden_markers += (
            "NO_BL1_IMAGE",
            "IMAGE_ORDER_BAD",
            "IMAGE_LEN_ZERO",
            "IMAGE_LEN_ALIGN",
            "IMAGE_HASH_MISMATCH",
            "TOC_REGION_OOB=",
            "TOC_PLEN_MISMATCH=",
            "BAD_IMAGE_TYPE",
            "BL1_ADDR_RANGE",
            "BL1_ENTRY_RANGE",
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
            slot,
            _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)],
            index,
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
        assert pm.entry_type(buf, entries[1]) == pm.IMAGE_TYPE_SEP_BL1, (
            "SEP_BL1 is not backup TOC entry 1, so the payload does not exercise "
            "position independence"
        )
        self.logger.info(
            "CHK-STIMULUS-REORDER: backup TOC is now [0x%x @%d len %d, SEP_BL1 @%d "
            "len %d]; TOC region %d bytes, payload_hashed_length %d, "
            "payload_length unchanged. BL1 body moved %d -> %d, so COPY_SRC must "
            "read 0x%08x instead of 0x%08x",
            geo["lead_type"],
            geo["lead_offset"],
            geo["lead_length"],
            geo["bl1_offset_after"],
            geo["bl1_length"],
            geo["toc_region"],
            geo["payload_hashed_length"],
            geo["bl1_offset_before"],
            geo["bl1_offset_after"],
            self._copy_src,
            before,
        )
        self.logger.info("CHK-STIMULUS-BL1-AFTER:  %s", pm.describe_bl1(buf, "backup"))

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "package_id", _REJECT_INDEX)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

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
            f"{want} appeared more than once; only one slot is handed off. Console: {console}"
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
            i_bsrc,
            _TWO_IMAGES,
            i_images,
            want,
            i_copy,
        )
