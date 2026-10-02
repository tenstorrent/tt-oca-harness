# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the TOC family: one planted TOC field per member.

``plant`` re-seals the slot and checks that it breaks exactly the named spec rule. The ROM
prints no marker for any TOC rule, so the error code and the served bytes carry the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd

_SEP_ROOT = Path(__file__).resolve().parents[4]
_DV_ROOT = Path(__file__).resolve().parents[3]
_BUILD = _SEP_ROOT / "bootrom" / "prod" / "build"

# One SEP_BL1 image; both slots of each image share one encryption state.
PLAINTEXT_IMAGE = str(_BUILD / "oca_secure_boot.bin")
ENCRYPTED_IMAGE = str(_BUILD / "oca_encrypted_boot.bin")
# BLMEMMAP, _VENDOR1 and SEP_BL1, stored in ascending offset order.
MULTI_IMAGE = str(_BUILD / "oca_multi_image_boot.bin")
ENCRYPTED_MULTI_IMAGE = str(_BUILD / "oca_encrypted_multi_image_boot.bin")
# One SEP_BL1 behind a zero-filled gap, so a TOC of up to 257 entries fits the payload.
TOC_CAP_IMAGE = str(_BUILD / "oca_toc_cap_boot.bin")
ENCRYPTED_TOC_CAP_IMAGE = str(_BUILD / "oca_encrypted_toc_cap_boot.bin")

_EFUSE_DIR = _DV_ROOT / "tb" / "efuse_preloads" / "efuse_configurations"
PLAINTEXT_EFUSE = _EFUSE_DIR / "sep_efuse_lc_prod.toml"
ENCRYPTED_EFUSE = _EFUSE_DIR / "sep_efuse_lc_prod_class_key.toml"

ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
ERR_PAYLOAD_TOC = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")
ERR_TOO_MANY_IMAGES = mm.boot_err("OCA_FAIL_PAYLOAD_TOO_MANY_IMAGES")

_BUILD_FLAGS = _BUILD / ".build_flags"

VERSION_MAJOR = "version_major"
IMAGE_COUNT = "image_count"
IMAGE_COUNT_CAP = "image_count_cap"
IMAGE_COUNT_AT_CAP = "image_count_at_cap"
OVERLAP = "images_overlap"
OFFSET_ALIGN = "entry_offset_align"
IMAGE_IN_TOC = "image_inside_toc"
TOC_PLEN = "toc_payload_length"

BAD_TOC_VERSION = pm.TOC_MAJOR_VERSION + 1
# Its entry array overruns the payload of every single-image golden.
BAD_IMAGE_COUNT = pm.TOC_MAX_IMAGE_COUNT + 1
# 8-byte aligned and past entry 0's digest field, so the image range never covers it.
IMAGE_IN_TOC_OFFSET = 240
# Above the manifest payload_length of every golden used here, cleartext or encrypted.
BAD_TOC_PAYLOAD_LENGTH = 0x2000
DESCENDING = (2, 1, 0)

_ENTRY0 = pm.toc_entry_at(0)


def _bytes(off: int, width: int) -> frozenset[int]:
    return frozenset(range(off, off + width))


def _entry_array(count: int) -> frozenset[int]:
    return _bytes(pm.TOC_HDR_SIZE, count * pm.TOC_ENTRY_SIZE)


def _entry_offset_and_digest(index: int) -> frozenset[int]:
    e = pm.toc_entry_at(index)
    return _bytes(e + pm.E_OFFSET, 8) | _bytes(e + pm.E_HASH, mm.DIGEST_LEN)


@dataclass(frozen=True)
class TocDefect:
    images: tuple[str, str]
    expected_error: int
    # Payload-relative (offset, width) the device must serve as planted.
    field: tuple[int, int]
    field_name: str
    mutate: Callable[[bytearray, str], str]
    rules: tuple[tuple[str, ...], tuple[str, ...]]
    # Payload-relative bytes the edit may change in the cleartext payload.
    allowed: frozenset[int]


def _both(*rules: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return rules, rules


def _mutate_version_major(buf: bytearray, slot: str) -> str:
    was = pm.set_toc_version_major(buf, slot, BAD_TOC_VERSION)
    assert was == pm.TOC_MAJOR_VERSION, (
        f"{slot} TOC major_version was {was} before the edit, not the supported "
        f"{pm.TOC_MAJOR_VERSION}; the golden is not the baseline this row raises"
    )
    return f"TOC major_version {was} -> {BAD_TOC_VERSION}, above the supported {was}"


def _mutate_image_count(buf: bytearray, slot: str) -> str:
    was = pm.set_toc_image_count(buf, slot, BAD_IMAGE_COUNT)
    return f"TOC image_count {was} -> {BAD_IMAGE_COUNT}, whose entry array overruns the payload"


def rom_toc_max_images() -> int:
    flags = [f for f in _BUILD_FLAGS.read_text().split() if f.startswith("OCA_TOC_MAX=")]
    assert len(flags) == 1, (
        f"{_BUILD_FLAGS} carries {flags} instead of one OCA_TOC_MAX= flag; rebuild the "
        f"boot ROM so the cap rows plant against the cap it was compiled with"
    )
    return int(flags[0].split("=", 1)[1], 0)


def _plant_count_near_cap(buf: bytearray, slot: str, count: int) -> str:
    cleartext = not pm.is_encrypted(buf, slot)
    was = pm.set_toc_image_count(buf, slot, count, reseal_entries=False, hashed_to_span=cleartext)
    span = pm.TOC_HDR_SIZE + count * pm.TOC_ENTRY_SIZE
    plain_len = len(pm.toc_plaintext(buf, slot))
    assert span <= plain_len, (
        f"{slot} TOC of {count} entries spans {span} bytes, past the {plain_len}-byte "
        f"payload: the fit rule would refuse it with OCA_FAIL_PAYLOAD_TOC before the cap"
    )
    hashed = (
        f"payload_hashed_length {pm.payload_hashed_length(buf, slot)} follows it"
        if cleartext
        else "payload_hashed_length still spans the ciphertext"
    )
    return (
        f"TOC image_count {was} -> {count} against the ROM cap of {rom_toc_max_images()}; "
        f"its {span}-byte entry array fits the {plain_len}-byte payload ({hashed}), and "
        f"entries 1.. read the zero-filled gap"
    )


def _mutate_image_count_cap(buf: bytearray, slot: str) -> str:
    return _plant_count_near_cap(buf, slot, rom_toc_max_images() + 1)


def _mutate_image_count_at_cap(buf: bytearray, slot: str) -> str:
    return _plant_count_near_cap(buf, slot, rom_toc_max_images())


def _mutate_overlap(buf: bytearray, slot: str) -> str:
    old = pm.permute_toc_entries(buf, slot, DESCENDING)
    permuted = bytes(buf)
    low = pm.toc_entry(buf, slot, 2)
    was = pm.set_toc_entry_offset(buf, slot, 1, low.offset + 8)
    # The permutation is legal on its own; only the entry 1 edit creates the overlap.
    moved = {i for r in pm.plaintext_diff(permuted, bytes(buf), slot) for i in r}
    assert moved and moved <= _entry_offset_and_digest(1), (
        f"{slot} overlap edit changed payload bytes {sorted(moved - _entry_offset_and_digest(1))} "
        f"beyond entry 1's offset and digest"
    )
    return (
        f"TOC stored in offset order {old}; entry 1 offset {was} -> {low.offset + 8}, "
        f"inside entry 2's [{low.offset}, {low.offset + low.length})"
    )


def _mutate_offset_align(buf: bytearray, slot: str) -> str:
    e0 = pm.toc_entry(buf, slot, 0)
    was = pm.set_toc_entry_offset(buf, slot, 0, e0.offset - 4)
    # offset - 4 still starts after the TOC and still ends inside the payload.
    return f"image 0 offset {was} -> {was - 4}, which is {(was - 4) % 8} modulo 8"


def _mutate_image_in_toc(buf: bytearray, slot: str) -> str:
    was = pm.set_toc_entry_offset(buf, slot, 0, IMAGE_IN_TOC_OFFSET)
    toc_end = pm.toc_entry_lower_bound(buf, slot, 0)
    assert IMAGE_IN_TOC_OFFSET < toc_end, (
        f"image 0 offset {IMAGE_IN_TOC_OFFSET} is not inside the {toc_end}-byte TOC"
    )
    return (
        f"image 0 offset {was} -> {IMAGE_IN_TOC_OFFSET}, inside the {toc_end}-byte TOC; "
        f"the spec places images after the TOC but lists no rule for it"
    )


def _mutate_toc_plen(buf: bytearray, slot: str) -> str:
    was = pm.set_toc_payload_length(buf, slot, BAD_TOC_PAYLOAD_LENGTH)
    return (
        f"TOC payload_length {was} -> {BAD_TOC_PAYLOAD_LENGTH} against the manifest's "
        f"{pm.manifest_payload_length(buf, slot)}"
    )


_SINGLE = (PLAINTEXT_IMAGE, ENCRYPTED_IMAGE)
DEFECTS: dict[str, TocDefect] = {
    VERSION_MAJOR: TocDefect(
        _SINGLE,
        ERR_PAYLOAD_TOC,
        (pm.TOC_OFF_MAJOR_VERSION, 2),
        "TOC major_version",
        _mutate_version_major,
        _both("version_major"),
        _bytes(pm.TOC_OFF_MAJOR_VERSION, 2),
    ),
    IMAGE_COUNT: TocDefect(
        _SINGLE,
        ERR_PAYLOAD_TOC,
        (pm.TOC_OFF_IMAGE_COUNT, 8),
        "TOC image_count",
        _mutate_image_count,
        # A cleartext payload_hashed_length cannot equal a span past payload_length.
        (("span_exceeds_payload", "hashed_length"), ("span_exceeds_payload",)),
        _bytes(pm.TOC_OFF_IMAGE_COUNT, 8),
    ),
    # The cap is a ROM build limit, not a spec rule: the two cap rows differ only in count.
    IMAGE_COUNT_CAP: TocDefect(
        (TOC_CAP_IMAGE, ENCRYPTED_TOC_CAP_IMAGE),
        ERR_TOO_MANY_IMAGES,
        (pm.TOC_OFF_IMAGE_COUNT, 8),
        "TOC image_count",
        _mutate_image_count_cap,
        _both("length_zero"),
        _bytes(pm.TOC_OFF_IMAGE_COUNT, 8),
    ),
    IMAGE_COUNT_AT_CAP: TocDefect(
        (TOC_CAP_IMAGE, ENCRYPTED_TOC_CAP_IMAGE),
        ERR_PAYLOAD_TOC,
        (pm.TOC_OFF_IMAGE_COUNT, 8),
        "TOC image_count",
        _mutate_image_count_at_cap,
        _both("length_zero"),
        _bytes(pm.TOC_OFF_IMAGE_COUNT, 8),
    ),
    OVERLAP: TocDefect(
        (MULTI_IMAGE, ENCRYPTED_MULTI_IMAGE),
        ERR_PAYLOAD_TOC,
        (pm.toc_entry_at(1) + pm.E_OFFSET, 8),
        "TOC entry 1 offset",
        _mutate_overlap,
        _both("overlap"),
        _entry_array(len(DESCENDING)),
    ),
    OFFSET_ALIGN: TocDefect(
        _SINGLE,
        ERR_PAYLOAD_TOC,
        (_ENTRY0 + pm.E_OFFSET, 8),
        "TOC entry 0 offset",
        _mutate_offset_align,
        _both("offset_align"),
        _entry_offset_and_digest(0),
    ),
    IMAGE_IN_TOC: TocDefect(
        _SINGLE,
        ERR_PAYLOAD_TOC,
        (_ENTRY0 + pm.E_OFFSET, 8),
        "TOC entry 0 offset",
        _mutate_image_in_toc,
        _both(),
        _entry_offset_and_digest(0),
    ),
    TOC_PLEN: TocDefect(
        _SINGLE,
        ERR_PAYLOAD_TOC,
        (pm.TOC_OFF_PAYLOAD_LENGTH, 8),
        "TOC payload_length",
        _mutate_toc_plen,
        _both("toc_plen_mismatch"),
        _bytes(pm.TOC_OFF_PAYLOAD_LENGTH, 8),
    ),
}


def image_for(field: str, encrypted: bool) -> str:
    return DEFECTS[field].images[int(encrypted)]


def efuse_for(encrypted: bool) -> Path:
    return ENCRYPTED_EFUSE if encrypted else PLAINTEXT_EFUSE


def assert_encryption(buf, encrypted: bool, image: str) -> None:
    for slot in ("primary", "backup"):
        got = pm.is_encrypted(buf, slot)
        assert got == encrypted, (
            f"{slot} payload encrypted_payload flag is {int(got)} but this member "
            f"declares encrypted={encrypted}; the loaded image ({image}) is not the "
            f"one this cell is about"
        )


def assert_reaches_payload(buf, slot: str) -> None:
    major, minor = mm.manifest_version(buf, slot)
    assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
        f"{slot} manifest version is {major}.{minor}: the slot would be refused on its "
        f"format version before the TOC is ever parsed"
    )
    assert mm.manifest_length(buf, slot) == mm.MANIFEST_SIZE, (
        f"{slot} manifest_length is {mm.manifest_length(buf, slot)}, expected "
        f"{mm.MANIFEST_SIZE}: MANIFEST_LENGTH would preempt the TOC arm"
    )


def plant(logger, buf: bytearray, slot: str, field: str) -> bytes:
    d = DEFECTS[field]
    assert_reaches_payload(buf, slot)
    golden = bytes(buf)
    detail = d.mutate(buf, slot)
    violations = pm.spec_rule_violations(buf, slot)
    rules = list(d.rules[int(pm.is_encrypted(buf, slot))])
    assert violations == rules, (
        f"{slot} TOC breaks {violations}, expected exactly {rules}: another "
        f"rule could refuse the slot with the same code"
    )
    changed = {i for r in pm.plaintext_diff(golden, bytes(buf), slot) for i in r}
    assert changed and changed <= d.allowed, (
        f"{slot} {field} edit changed cleartext payload bytes "
        f"{sorted(changed - d.allowed)[:16]} outside the bytes it may touch"
    )
    off, width = d.field
    p = pm.payload_base(buf, slot)
    # For an encrypted slot this is ciphertext, the only form the flash device holds.
    stored = bytes(buf[p + off : p + off + width])
    logger.info(
        "CHK-STIMULUS-TOC: %s %s (payload is %s): %s. spec rules broken: %s; cleartext "
        "bytes changed: %d, all inside the edited field and the digests it refreshes. "
        "%s sits at flash 0x%06x and the device must serve %s there",
        slot,
        field,
        "ENCRYPTED" if pm.is_encrypted(buf, slot) else "plaintext",
        detail,
        violations,
        len(changed),
        d.field_name,
        p + off,
        stored.hex(),
    )
    return stored


def assert_served(logger, flash, slot: str, field: str, expected: bytes, payload_offset: int):
    d = DEFECTS[field]
    fd.assert_served_field(
        logger, flash, slot, payload_offset + d.field[0], expected, f"{slot} {d.field_name}"
    )
