# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_BL1 is not the first TOC image; the primary boots anyway.

the position-independence case. The ROM must locate BL1 by TYPE,
and it does so twice on the way to a boot: ``validate_manifest_payload`` scans
every entry for ``IMAGE_TYPE_SEP_BL1`` before it will accept the slot, and
``find_toc_entry`` scans again at handoff (``bootrom/prod/src/manifest_load.c``,
``bootrom/prod/src/rom_handoff.c``). The required behaviour is an ordinary
completed boot with no warning when SEPBL1 is present but not first.

THE STIMULUS IS AN INSERT, NOT A PERMUTATION. ``secure_boot.bin`` declares exactly
ONE image, the BL1 (``image_count`` is 1), so permuting the ``payload_images`` list
would change nothing and a permutation stimulus is inexpressible against this
image. ``sep_payload_mutate.insert_leading_image``
creates the second image instead: ``image_count`` becomes 2, a SEPBL2 entry takes
index 0, and the BL1 entry moves to index 1 with its body relocated to sit behind
the new one. The property under test is preserved and made stronger -- index 0 now
holds an image that is NOT the BL1, so a ROM that assumed ``images[0]`` would fail
rather than accidentally succeed. Everything else about the slot is unchanged: same
``payload_length``, same TOC/manifest length agreement, same BL1 ``load_addr``,
``entry_point``, ``length`` and body bytes.

WHAT MAKES A PASSING RUN DISTINGUISHABLE FROM AN ORDINARY BOOT, which is the real
risk for a positive testcase whose expected console is a plain boot sequence. Two
console values that only this stimulus can produce, both asserted below:

  * ``IMAGES=0x00000002``. ``rom_manifest_boot`` prints the accepted slot's
    ``toc->image_count`` right after ``MANIFEST_OK`` (``manifest_load.c``), and every
    other testcase in this directory runs against a one-image payload, so their logs
    read ``IMAGES=0x00000001``;
  * ``COPY_SRC=`` at the RELOCATED BL1 address. ``rom_handoff_bl1`` prints
    ``(uint8_t *)toc + bl1->offset`` (``rom_handoff.c``), so the ROM can only print
    the new address by having read TOC entry 1's ``offset``. That is the position
    independence itself, not a proxy for it.

The negative half is the forbidden list: ``NO_BL1_IMAGE`` is what a position-
dependent ROM would print here, and ``IMAGE_ORDER_BAD``/``IMAGE_HASH_MISMATCH``/
``TOC_REGION_OOB=`` are what a mis-built insert would produce. The backup slot is
forbidden outright: no warning and no failover, so this run
must never read ``MANIFEST_SRC=0x00041000``.

The run uses the PROD OTP preload, so secure boot is enforced by lifecycle rather
than chosen by the manifest flag (``secure_boot_enabled``, ``manifest_load.c``);
that matches the rest of this ported family and means the re-sealed slot's signature
really is checked.
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
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_TWO_IMAGES = "IMAGES=0x00000002"


@pyuvm.test()
class sep_firmware_manifest_primary_reordered_sepbl1_test(
        sep_rom_ot_secure_boot_test):
    """Primary TOC is [SEPBL2, SEPBL1]; the ROM finds BL1 at index 1 and boots."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        _TWO_IMAGES, "BL1_COPIED", "BL1_JUMP=", "PLD_HASH_OK",
    )
    # No slot may be refused, nothing may fall over to the backup, and none of the
    # TOC verdicts a mis-built payload would produce may appear.
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "NO_BL1_IMAGE",
        "IMAGE_ORDER_BAD", "IMAGE_LEN_ZERO", "IMAGE_LEN_ALIGN",
        "IMAGE_HASH_MISMATCH", "TOC_REGION_OOB=", "TOC_PLEN_MISMATCH=",
        "BAD_IMAGE_TYPE", "BL1_ADDR_RANGE", "BL1_ENTRY_RANGE",
        "MANIFEST_HASH_MISMATCH", "PLD_HASH_MISMATCH", "CRYPTO_FAIL=",
        fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
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
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x", lc, sboot_dis,
            image.field_int("BL1_VERSION"), image.field_int("CHIPLET_PUBK_REVOKE"),
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
        assert pm._u64(buf, entries[1] + pm.E_TYPE) == pm.IMAGE_TYPE_SEP_BL1, (
            "SEP_BL1 is not TOC entry 1, so the payload does not exercise position "
            "independence"
        )
        # The whole claim is that a still-VALID slot booted from a non-zero BL1
        # index. verify_sealed reproduces the ROM's structural and cryptographic
        # checks, verify_public_key proves the modulus is the one the ROM binds to.
        pm.verify_sealed(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-REORDER: primary TOC is now [0x%x @%d len %d, "
            "SEP_BL1 @%d len %d]; TOC region %d bytes, payload_hashed_length %d, "
            "payload_length unchanged. BL1 body moved %d -> %d, so COPY_SRC must "
            "read 0x%08x instead of 0x%08x",
            geo["lead_type"], geo["lead_offset"], geo["lead_length"],
            geo["bl1_offset_after"], geo["bl1_length"], geo["toc_region"],
            geo["payload_hashed_length"], geo["bl1_offset_before"],
            geo["bl1_offset_after"], self._copy_src, self._copy_src_before,
        )
        self.logger.info("CHK-STIMULUS-BL1-AFTER:  %s", pm.describe_bl1(buf, "primary"))
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        # CHK-POSITION-INDEPENDENT: the ROM copied BL1 from the address TOC entry 1
        # names. This is the property under test rather than a proxy: the value can
        # only be produced by reading entry 1's offset, and it is not the address
        # any other testcase's payload puts BL1 at.
        want = f"COPY_SRC=0x{self._copy_src:08x}"
        i_copy = fd.first_index(console, want)
        assert i_copy >= 0, (
            f"ROM never printed {want}. The BL1 body sits at payload offset "
            f"{self._geometry['bl1_offset_after']} and TOC entry 1 names it, so a "
            f"ROM that scanned the TOC by type must copy from there. Console: "
            f"{console}"
        )
        assert fd.count(console, want) == 1, (
            f"{want} appeared more than once; only one slot is read in this run. "
            f"Console: {console}"
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
            i_ok, _TWO_IMAGES, i_images, want, i_copy,
        )
