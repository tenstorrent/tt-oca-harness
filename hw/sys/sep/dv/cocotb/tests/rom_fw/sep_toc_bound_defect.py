# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the TOC/manifest length agreement and the entry-0 bound.

Plants either a TOC payload_length above the manifest's or an entry-0 offset inside
the TOC region; the IMAGE_OOB arms are forbidden, not planted.
"""

from __future__ import annotations

from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw import sep_toc_entry_defect as ted

PLAINTEXT_IMAGE = td.PLAINTEXT_IMAGE
ENCRYPTED_IMAGE = td.ENCRYPTED_IMAGE
PLAINTEXT_EFUSE = td.PLAINTEXT_EFUSE
ENCRYPTED_EFUSE = td.ENCRYPTED_EFUSE

# Both slots of an image share one encryption state, so a primary encrypted cell decrypts twice.

ERR_BAD_LENGTH = td.ERR_BAD_LENGTH
ERR_IMAGE_OOB = ted.ERR_IMAGE_OOB
ERR_IMAGE_OVERLAP = ted.ERR_IMAGE_OVERLAP
ERR_BAD_MAGIC = td.ERR_BAD_MAGIC

BOUND = "payload_image_exceeds_bound"
PLEN = "toc_payload_size_mismatch"

# Must stay 8-byte aligned and below the 248-byte TOC region, or another check fires.
BOUND_IMAGE_OFFSET = 240
BOUND_ENTRY_INDEX = 0

# Above the manifest length on both slot types.
BAD_TOC_PAYLOAD_LENGTH = 0x2000

DEFECT_TOKEN = {
    BOUND: f"IMAGE_ORDER_BAD idx=0x{BOUND_ENTRY_INDEX:08x}",
    PLEN: "TOC_PLEN_MISMATCH=",
}
# Prefixes as spelled in td.OTHER_PAYLOAD_TOKENS, so each family can drop only its own.
_TOKEN_PREFIX = {BOUND: "IMAGE_ORDER_BAD", PLEN: "TOC_PLEN_MISMATCH="}
EXPECTED_ERROR = {BOUND: ERR_IMAGE_OVERLAP, PLEN: ERR_BAD_LENGTH}
# (payload-relative offset, width) of the mutated field.
FIELD = {
    BOUND: (pm.toc_entry_at(BOUND_ENTRY_INDEX) + pm.E_OFFSET, 8),
    PLEN: (pm.TOC_OFF_PAYLOAD_LENGTH, 8),
}
FIELD_NAME = {BOUND: "image 0 offset", PLEN: "TOC payload_length"}

# sep_toc_entry_defect's ordering row prints the same prefix, so forbid its exact token.
FOREIGN_TOKENS = {
    BOUND: (ted.DEFECT_TOKEN[ted.ORDER],),
    PLEN: (),
}

DECRYPT_START = td.DECRYPT_START
DECRYPT_OK = td.DECRYPT_OK

# Plaintext rows must not decrypt, and encrypted rows must decrypt to reach the checked arm.
DECRYPT_FAILURE_TOKENS = td.DECRYPT_FAILURE_TOKENS


def sibling_error(defect: str) -> int:
    return EXPECTED_ERROR[PLEN if defect == BOUND else BOUND]


def other_payload_tokens(defect: str) -> tuple[str, ...]:
    mine = _TOKEN_PREFIX[defect]
    if mine not in td.OTHER_PAYLOAD_TOKENS:
        raise AssertionError(
            f"{mine!r} is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so this "
            f"family's token would be neither required by one row nor forbidden by "
            f"its sibling; the swap-test defence has silently lapsed"
        )
    return tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != mine) + FOREIGN_TOKENS[defect]


def neighbouring_errors(defect: str, *, exclude: tuple[int, ...] = ()) -> list[str]:
    codes = (
        sibling_error(defect),
        ERR_IMAGE_OOB,
        ted.ERR_BAD_IMAGE_TYPE,
        ted.ERR_IMAGE_HASH_MISMATCH,
        td.ERR_BAD_MAGIC,
        td.ERR_BAD_VERSION,
        td.ERR_BAD_LENGTH,
        td.ERR_BAD_TOC_ID,
        td.ERR_BAD_TOC_VERSION,
        td.ERR_TOC_COUNT,
        td.ERR_PAYLOAD_TOO_LARGE,
        td.ERR_NO_BL1_IMAGE,
    )
    # exclude admits codes produced elsewhere, e.g. the backup family's primary BAD_MAGIC.
    drop = set(exclude) | {EXPECTED_ERROR[defect]}
    return [f"MANIFEST_ERR=0x{c:08x}" for c in codes if c not in drop]


def plant(logger, buf: bytearray, slot: str, defect: str) -> bytes:
    if defect not in DEFECT_TOKEN:
        raise ValueError(f"unknown defect {defect!r}; expected one of {list(DEFECT_TOKEN)}")
    encrypted = pm.is_encrypted(buf, slot)
    off, size = FIELD[defect]
    p_len = pm.manifest_payload_length(buf, slot)

    if defect == BOUND:
        bound = pm.toc_entry_lower_bound(buf, slot, BOUND_ENTRY_INDEX)
        was = pm.set_toc_entry_offset(buf, slot, BOUND_ENTRY_INDEX, BOUND_IMAGE_OFFSET)
        detail = (
            f"image {BOUND_ENTRY_INDEX} offset 0x{was:x} -> "
            f"0x{BOUND_IMAGE_OFFSET:x}, which is BELOW the {bound}-byte TOC "
            f"region the ROM seeds prev_end with, so the declared body would "
            f"begin inside the metadata being parsed; its digest was "
            f"recomputed over the newly declared range"
        )
        expect = BOUND_IMAGE_OFFSET
    else:
        was = pm.set_toc_payload_length(buf, slot, BAD_TOC_PAYLOAD_LENGTH)
        detail = (
            f"TOC payload_length {was} -> {BAD_TOC_PAYLOAD_LENGTH}, against "
            f"the manifest's {p_len}; the TOC claims "
            f"{BAD_TOC_PAYLOAD_LENGTH - p_len} bytes MORE than were loaded"
        )
        expect = BAD_TOC_PAYLOAD_LENGTH

    p = pm.payload_base(buf, slot)
    # For an encrypted slot this is ciphertext, the only form the flash device holds.
    stored = bytes(buf[p + off : p + off + size])
    now = int.from_bytes(bytes(pm.toc_plaintext(buf, slot)[off : off + size]), "little")
    if now != expect:
        raise AssertionError(
            f"{slot} TOC {FIELD_NAME[defect]} reads 0x{now:x} after the mutation, "
            f"expected 0x{expect:x}; the mutation did not land"
        )
    logger.info(
        "CHK-STIMULUS-TOC-BOUND: %s %s (payload is %s). %s. The field sits at flash "
        "0x%06x and the device must serve %s there. Every other TOC rule is left "
        "SATISFIED -- identifier PTOC, major_version %d, image_count inside "
        "0 < n <= %d, every image type known, every declared range inside the "
        "payload and matching its own digest -- so %s is the only rule "
        "validate_manifest_payload can refuse this slot on",
        slot,
        defect,
        "ENCRYPTED" if encrypted else "plaintext",
        detail,
        p + off,
        stored.hex(),
        pm.TOC_MAJOR_VERSION,
        pm.TOC_MAX_IMAGE_COUNT,
        DEFECT_TOKEN[defect].rstrip("=").split(" idx=")[0],
    )
    return stored


def assert_served_bound_field(
    logger, flash, slot: str, defect: str, expected: bytes, payload_offset: int
) -> None:
    off, _size = FIELD[defect]
    # Encrypted slots hold identical ciphertext here; only the flash address names the slot.
    fd.assert_served_field(
        logger,
        flash,
        slot,
        payload_offset + off,
        expected,
        f"{slot} {FIELD_NAME[defect]}",
    )
