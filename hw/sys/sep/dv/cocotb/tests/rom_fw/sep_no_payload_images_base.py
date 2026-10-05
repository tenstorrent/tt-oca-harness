# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the three tests whose manifest declares no payload images.

Plants ``toc->image_count = 0`` in a plaintext slot. The library refuses it with the
silent ``OCA_FAIL_PAYLOAD_TOC`` after that slot's signature has verified.
"""

from __future__ import annotations

import pyuvm  # noqa: F401
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import (
    PAYLOAD_STAGE_MARKERS,
    err_marker,
    sep_backup_payload_fail_base,
)
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

EMPTY_IMAGE_COUNT = 0
ERR_EMPTY_TOC = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")
ERR_PAYLOAD_HASH = mm.boot_err("OCA_FAIL_PAYLOAD_HASH")

# A plaintext slot refused in its payload stage prints none of these.
PLAINTEXT_PAYLOAD_ABSENT = PAYLOAD_STAGE_MARKERS + ("DECRYPT_OK",)

IMAGE_COUNT_FIELD = (pm.TOC_OFF_IMAGE_COUNT, 8)
ENTRY0_DIGEST_FIELD = (pm.toc_entry_at(0) + pm.E_HASH, 32)


def assert_plaintext_image(buf: bytearray, image: str) -> None:
    for slot in ("primary", "backup"):
        assert not pm.is_encrypted(buf, slot), (
            f"{slot} payload carries encrypted_payload = 1; these tests use the "
            f"PLAINTEXT stimulus and the loaded image ({image}) is not plaintext"
        )


def plant_empty_image_list(logger, buf: bytearray, slot: str) -> bytes:
    major, minor = mm.manifest_version(buf, slot)
    assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
        f"{slot} manifest version is {major}.{minor}: the slot would be refused on "
        f"its format version before the TOC is ever parsed"
    )
    assert mm.manifest_length(buf, slot) == mm.MANIFEST_SIZE, (
        f"{slot} manifest_length is {mm.manifest_length(buf, slot)}, expected "
        f"{mm.MANIFEST_SIZE}: MANIFEST_LENGTH would preempt the TOC arm"
    )
    off, size = IMAGE_COUNT_FIELD
    golden = bytes(buf)
    # payload_hashed_length follows the header-only span, so count_zero is the only rule broken.
    was = pm.set_toc_image_count(buf, slot, EMPTY_IMAGE_COUNT, hashed_to_span=True)
    assert was > 0, (
        f"{slot} TOC already declared {was} images before the mutation, so the "
        f"mutation would not change the count the ROM reads"
    )
    p = pm.payload_base(buf, slot)
    stored = bytes(buf[p + off : p + off + size])
    # Pin literal zero: an over-large count returns the same code and is covered elsewhere.
    assert EMPTY_IMAGE_COUNT == 0 and stored == bytes(size), (
        f"{slot} TOC image_count was planted as {EMPTY_IMAGE_COUNT} and stored as "
        f"{stored.hex()}; these tests cover a zero count; an over-large count is "
        f"covered by sep_toc_defect.BAD_IMAGE_COUNT"
    )
    violations = pm.spec_rule_violations(buf, slot)
    assert violations == ["count_zero"], (
        f"{slot} TOC breaks {violations}, expected only ['count_zero']: another rule "
        f"could refuse the slot with the same code"
    )
    changed = {i for r in pm.plaintext_diff(golden, bytes(buf), slot) for i in r}
    assert changed and changed <= set(range(off, off + size)), (
        f"{slot} image_count edit changed cleartext payload bytes {sorted(changed)[:16]} "
        f"outside the field"
    )
    logger.info(
        "CHK-STIMULUS-NO-PAYLOAD-IMAGES: %s TOC image_count %d -> %d, the only spec "
        "rule the slot breaks (%s). The field sits at flash 0x%06x and the device "
        "must serve %s there; payload_hashed_length is %d, the header-only span, and "
        "payload_hash and the signature are recomputed over the edit",
        slot,
        was,
        EMPTY_IMAGE_COUNT,
        violations,
        p + off,
        stored.hex(),
        pm.payload_hashed_length(buf, slot),
    )
    return stored


def plant_stale_payload_hash(logger, buf: bytearray, slot: str) -> bytes:
    entries = pm.toc_entries(buf, slot)
    assert len(entries) == 1, (
        f"{slot} TOC declares {len(entries)} images; entry 0 is the whole list only "
        f"when the payload carries one"
    )
    at, size = ENTRY0_DIGEST_FIELD
    hashed = pm.payload_hashed_length(buf, slot)
    assert at + size <= hashed, (
        f"payload_hashed_length {hashed} does not reach entry 0's digest at "
        f"{at}..{at + size}: payload_hash would not cover the edit"
    )
    served = pm.corrupt_toc_entry_hash(buf, slot, 0, value=bytes(size), reseal=False)
    # The manifest-side seals still hold and payload_hash alone is stale.
    mm.verify_layout(buf, slot)
    pm.verify_signing_key(buf, slot)
    try:
        pm.verify_sealed(buf, slot, check_toc=False)
    except AssertionError as e:
        assert "payload_hash does not cover" in str(e), f"unexpected seal failure: {e}"
    else:
        raise AssertionError(f"{slot} payload_hash still covers the edited payload")
    logger.info(
        "CHK-STIMULUS-STALE-PAYLOAD-HASH: %s TOC entry 0 digest -> %s with nothing "
        "re-sealed; manifest_hash and the signature verify, payload_hash does not",
        slot,
        served.hex(),
    )
    return served


class sep_no_payload_images_primary_base(sep_primary_fail_backup_boot_base):
    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_EMPTY_TOC
    primary_defect_marker = err_marker(ERR_EMPTY_TOC)
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_absent = PLAINTEXT_PAYLOAD_ABSENT
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert_plaintext_image(buf, self.flash_image)
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        self._served = plant_empty_image_list(self.logger, buf, "primary")

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        off, _size = IMAGE_COUNT_FIELD
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            self._payload_offset + off,
            self._served,
            "primary TOC image_count",
        )


class sep_no_payload_images_terminal_base(sep_backup_payload_fail_base):
    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    expected_error = ERR_EMPTY_TOC
    backup_defect_marker = err_marker(ERR_EMPTY_TOC)
    backup_absent = ("DECRYPT_OK",)
    # Payload-relative (offset, size) of the primary's planted field.
    primary_field: tuple[int, int] = IMAGE_COUNT_FIELD

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert_plaintext_image(buf, self.flash_image)
        self._primary_payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        self._backup_payload_offset = pm.payload_base(buf, "backup") - mm.slot_base("backup")
        return super().mutate_flash_image(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        self._backup_served = plant_empty_image_list(self.logger, buf, "backup")

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        off, _size = IMAGE_COUNT_FIELD
        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            self._backup_payload_offset + off,
            self._backup_served,
            "backup TOC image_count",
        )
        p_off, _p_size = self.primary_field
        fd.assert_served_field(
            self.logger,
            self._flash,
            "primary",
            self._primary_payload_offset + p_off,
            self._primary_served,
            "primary's failover-trigger field",
        )
