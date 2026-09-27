# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_BL1 is not the first TOC image; the primary boots anyway.

A SEPBL2 image is inserted at TOC index 0, so the ROM must find BL1 by type: the
run must print IMAGES=0x00000002 and COPY_SRC= at the relocated BL1 address.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_TWO_IMAGES = "IMAGES=0x00000002"


@pyuvm.test()
class sep_firmware_manifest_primary_reordered_sepbl1_test(sep_rom_ot_secure_boot_test):
    """Primary TOC is [SEPBL2, SEPBL1]; the ROM finds BL1 at index 1 and boots."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        _TWO_IMAGES,
        "BL1_COPIED",
        "BL1_JUMP=",
        "PLD_HASH_OK",
    )
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
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
        "MANIFEST_HASH_MISMATCH",
        "PLD_HASH_MISMATCH",
        "CRYPTO_FAIL=",
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
    )

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced or the re-sealed slot's signature is never checked"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        fd.assert_clean_key_fuses(image)
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self.logger.info("CHK-STIMULUS-BL1-BEFORE: %s", pm.describe_bl1(buf, "primary"))
        self._copy_src_before = pm.bl1_sram_source(buf, "primary")
        geo = pm.insert_leading_image(buf, "primary")
        self._geometry = geo
        self._copy_src = pm.bl1_sram_source(buf, "primary")
        assert self._copy_src != self._copy_src_before, (
            "the BL1 body did not move, so COPY_SRC= would be the same value an "
            "ordinary boot prints and could not discriminate this run"
        )
        entries = pm.toc_entries(buf, "primary")
        assert len(entries) == 2, f"primary TOC has {len(entries)} images, expected 2"
        assert pm.entry_type(buf, entries[1]) == pm.IMAGE_TYPE_SEP_BL1, (
            "SEP_BL1 is not TOC entry 1, so the payload does not exercise position independence"
        )
        # The relocated slot must still pass the ROM's structural and signature checks.
        pm.verify_sealed(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-REORDER: primary TOC is now [0x%x @%d len %d, "
            "SEP_BL1 @%d len %d]; TOC region %d bytes, payload_hashed_length %d, "
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
            self._copy_src_before,
        )
        self.logger.info("CHK-STIMULUS-BL1-AFTER:  %s", pm.describe_bl1(buf, "primary"))
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        want = f"COPY_SRC=0x{self._copy_src:08x}"
        i_copy = fd.first_index(console, want)
        assert i_copy >= 0, (
            f"ROM never printed {want}. The BL1 body sits at payload offset "
            f"{self._geometry['bl1_offset_after']} and TOC entry 1 names it, so a "
            f"ROM that scanned the TOC by type must copy from there. Console: "
            f"{console}"
        )
        assert fd.count(console, want) == 1, (
            f"{want} appeared more than once; only one slot is read in this run. Console: {console}"
        )
        i_images = fd.first_index(console, _TWO_IMAGES)
        i_ok = fd.first_index(console, "MANIFEST_OK")
        assert 0 <= i_ok < i_images < i_copy, (
            f"MANIFEST_OK@{i_ok} -> {_TWO_IMAGES}@{i_images} -> {want}@{i_copy} is "
            f"not the order rom_manifest_boot and rom_handoff_bl1 emit; the "
            f"accepted slot is not the two-image one. Console: {console}"
        )
        self.logger.info(
            "CHK-BL1-BY-TYPE: MANIFEST_OK@%d -> %s@%d -> %s@%d -- the accepted "
            "payload declared two images and the ROM copied BL1 from TOC entry 1's "
            "offset, so it located BL1 by type and not by position",
            i_ok,
            _TWO_IMAGES,
            i_images,
            want,
            i_copy,
        )
