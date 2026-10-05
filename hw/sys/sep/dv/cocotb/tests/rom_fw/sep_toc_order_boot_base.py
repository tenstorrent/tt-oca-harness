# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base for primary boots from a three-image payload whose TOC a member stores in its own order.

Each arrangement breaks no spec rule, so the ROM must accept the slot and copy BL1 from the
offset its own entry names.
"""

from __future__ import annotations

import os

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import PLACEMENT_MARKERS
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_SLOT = "primary"


def bl1_index(buf, slot: str) -> int:
    count = int.from_bytes(pm.toc_plaintext(buf, slot)[pm.TOC_OFF_IMAGE_COUNT :][:8], "little")
    types = [pm.toc_entry(buf, slot, i).type for i in range(count)]
    assert types.count(pm.IMAGE_TYPE_SEP_BL1) == 1, f"{slot} TOC types {types}"
    return types.index(pm.IMAGE_TYPE_SEP_BL1)


def copy_src(buf, slot: str) -> int:
    rel = pm.payload_base(buf, slot) - mm.slot_base(slot)
    return pm.SEP_SRAM_BASE + rel + pm.toc_entry(buf, slot, bl1_index(buf, slot)).offset


class sep_toc_order_boot_base(sep_rom_ot_secure_boot_test):
    encrypted: bool = False

    def __init_subclass__(cls, **kwargs) -> None:
        cls.flash_image = td.ENCRYPTED_MULTI_IMAGE if cls.encrypted else td.MULTI_IMAGE
        cls.efuse_preload = td.efuse_for(cls.encrypted)
        super().__init_subclass__(**kwargs)

    def arrange_toc(self, buf: bytearray) -> str:
        raise NotImplementedError

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        assert image.lc_raw() == 0x1 and image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK == 0, (
            f"LC raw 0x{image.lc_raw():x}, SBOOT_DIS {image.field_int('SBOOT_DIS')}: the "
            f"run must enforce secure boot, or the rearranged slot's seals are never checked"
        )
        fd.assert_clean_key_fuses(image)
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        td.assert_encryption(buf, self.encrypted, self.flash_image)
        golden = bytes(buf)
        detail = self.arrange_toc(buf)
        pm.verify_sealed(buf, _SLOT)
        mm.verify_public_key(buf, _SLOT)
        violations = pm.spec_rule_violations(buf, _SLOT)
        assert violations == [], f"{_SLOT} TOC breaks {violations}; it must be a legal layout"
        count = len(td.DESCENDING)
        changed = {i for r in pm.plaintext_diff(golden, bytes(buf), _SLOT) for i in r}
        outside = changed - set(range(pm.TOC_HDR_SIZE, pm.toc_entry_at(count)))
        assert not outside, f"{_SLOT} rearrangement changed image bytes {sorted(outside)[:16]}"
        self._copy_src = copy_src(buf, _SLOT)
        self.logger.info(
            "CHK-STIMULUS-TOC-ORDER: %s (payload is %s); stored offsets %s, SEP_BL1 at "
            "index %d. The slot is re-sealed and breaks no spec rule, so the ROM must "
            "copy BL1 from 0x%08x",
            detail,
            "ENCRYPTED" if self.encrypted else "plaintext",
            [pm.toc_entry(buf, _SLOT, i).offset for i in range(count)],
            bl1_index(buf, _SLOT),
            self._copy_src,
        )
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected the primary "
            f"only: the rearranged slot must be accepted on its first read"
        )
        want = f"COPY_SRC=0x{self._copy_src:08x}"
        ordered = ("PUBK_AUTHORIZED", "RSA_EXEC", "RSA_VERIFY_OK", "MANIFEST_OK")
        ordered += ("DECRYPT_OK",) if self.encrypted else ()
        ordered += ("PAYLOAD_OK", want, "BL1_COPIED", "BL1_JUMP=")
        oc.assert_attempt(
            attempts[0], error=None, stage="accepted", ordered=ordered, absent=PLACEMENT_MARKERS
        )
        assert oc.count(console, "COPY_SRC=") == 1, f"COPY_SRC= printed more than once: {console}"
        self.logger.info(
            "CHK-BL1-BY-TYPE PASS: primary accepted after %s; BL1 copied from its own "
            "entry's offset",
            " -> ".join(ordered),
        )
