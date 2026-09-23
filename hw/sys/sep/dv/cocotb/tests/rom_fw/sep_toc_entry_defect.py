# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the two announced per-image arms of the TOC loop.

Plants an out-of-order image 1 offset or a misaligned image 0 length and checks the
indexed token, the error code, and the bytes the flash device served at that field.
"""

from __future__ import annotations

from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td

PLAINTEXT_IMAGE = td.PLAINTEXT_IMAGE
ENCRYPTED_IMAGE = td.ENCRYPTED_IMAGE
PLAINTEXT_EFUSE = td.PLAINTEXT_EFUSE
ENCRYPTED_EFUSE = td.ENCRYPTED_EFUSE

# Both slots of an image share one encryption state, so a primary encrypted cell decrypts twice.

ERR_BAD_IMAGE_TYPE = 0x0003_000D
ERR_IMAGE_OOB = 0x0003_000E
ERR_IMAGE_OVERLAP = 0x0003_000F
ERR_IMAGE_HASH_MISMATCH = 0x0003_0019
ERR_BAD_MAGIC = td.ERR_BAD_MAGIC

ORDER = "images_out_of_order"
SIZE = "invalid_payload_image_size"

SECOND_IMAGE_OFFSET = 0x500
# Entry 1 must end inside the payload, or the end > p_len arm fires before the ordering check.
SECOND_IMAGE_LENGTH = 256
SECOND_IMAGE_TYPE = pm.IMAGE_TYPE_SEP_BL2
ORDER_ENTRY_INDEX = 1

# Must end inside the payload, where end > p_len returns the same code.
BAD_IMAGE_LENGTH = 0x72D
SIZE_ENTRY_INDEX = 0

DEFECT_TOKEN = {
    ORDER: f"IMAGE_ORDER_BAD idx=0x{ORDER_ENTRY_INDEX:08x}",
    SIZE: f"IMAGE_LEN_ALIGN idx=0x{SIZE_ENTRY_INDEX:08x}",
}
# Prefixes as spelled in td.OTHER_PAYLOAD_TOKENS, so each family can drop only its own.
_TOKEN_PREFIX = {ORDER: "IMAGE_ORDER_BAD", SIZE: "IMAGE_LEN_ALIGN"}
EXPECTED_ERROR = {ORDER: ERR_IMAGE_OVERLAP, SIZE: ERR_IMAGE_OOB}
# (payload-relative offset, width) of the mutated TOC-entry field.
FIELD = {
    ORDER: (pm.toc_entry_at(ORDER_ENTRY_INDEX) + pm.E_OFFSET, 8),
    SIZE: (pm.toc_entry_at(SIZE_ENTRY_INDEX) + pm.E_LENGTH, 8),
}
FIELD_NAME = {ORDER: "image 1 offset", SIZE: "image 0 length"}

DECRYPT_START = td.DECRYPT_START
DECRYPT_OK = td.DECRYPT_OK

# Plaintext rows must not decrypt, and encrypted rows must decrypt to reach the TOC loop.
DECRYPT_FAILURE_TOKENS = td.DECRYPT_FAILURE_TOKENS


def sibling_error(defect: str) -> int:
    return EXPECTED_ERROR[SIZE if defect == ORDER else ORDER]


def other_payload_tokens(defect: str) -> tuple[str, ...]:
    mine = _TOKEN_PREFIX[defect]
    if mine not in td.OTHER_PAYLOAD_TOKENS:
        raise AssertionError(
            f"{mine!r} is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so this "
            f"family's token would be neither required by one row nor forbidden by "
            f"its sibling; the swap-test defence has silently lapsed"
        )
    return tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != mine)


def neighbouring_errors(defect: str, *, exclude: tuple[int, ...] = ()) -> list[str]:
    codes = (sibling_error(defect), ERR_BAD_IMAGE_TYPE, ERR_IMAGE_HASH_MISMATCH,
             td.ERR_BAD_MAGIC, td.ERR_BAD_VERSION, td.ERR_BAD_LENGTH,
             td.ERR_BAD_TOC_ID, td.ERR_BAD_TOC_VERSION, td.ERR_TOC_COUNT,
             td.ERR_PAYLOAD_TOO_LARGE, td.ERR_NO_BL1_IMAGE)
    # exclude admits codes produced elsewhere, e.g. the backup family's primary BAD_MAGIC.
    return [f"MANIFEST_ERR=0x{c:08x}" for c in codes if c not in exclude]


def plant(logger, buf: bytearray, slot: str, defect: str) -> bytes:
    if defect not in DEFECT_TOKEN:
        raise ValueError(f"unknown defect {defect!r}; expected one of {list(DEFECT_TOKEN)}")
    encrypted = pm.is_encrypted(buf, slot)
    off, size = FIELD[defect]

    if defect == ORDER:
        geometry = pm.make_images_out_of_order(
            buf, slot, second_offset=SECOND_IMAGE_OFFSET,
            second_length=SECOND_IMAGE_LENGTH, second_type=SECOND_IMAGE_TYPE)
        detail = (
            f"image_count 1 -> 2; entry 0 keeps SEP_BL1 at "
            f"0x{geometry['first_offset']:x} length 0x{geometry['first_length']:x}; "
            f"entry 1 is a SEPBL2 at 0x{geometry['second_offset']:x} length "
            f"0x{geometry['second_length']:x}, BELOW entry 0's end "
            f"0x{geometry['first_offset'] + geometry['first_length']:x}; "
            f"payload_hashed_length is {geometry['payload_hashed_length']}"
        )
        expect = SECOND_IMAGE_OFFSET
    else:
        was = pm.set_toc_entry_length(buf, slot, SIZE_ENTRY_INDEX, BAD_IMAGE_LENGTH)
        detail = (f"image 0 length 0x{was:x} -> 0x{BAD_IMAGE_LENGTH:x}, which is "
                  f"{BAD_IMAGE_LENGTH % 4} modulo 4; its digest was recomputed over "
                  f"the newly declared range")
        expect = BAD_IMAGE_LENGTH

    p = pm.payload_base(buf, slot)
    # For an encrypted slot this is ciphertext, the only form the flash device holds.
    stored = bytes(buf[p + off:p + off + size])
    now = int.from_bytes(bytes(pm.toc_plaintext(buf, slot)[off:off + size]), "little")
    if now != expect:
        raise AssertionError(
            f"{slot} TOC {FIELD_NAME[defect]} reads 0x{now:x} after the mutation, "
            f"expected 0x{expect:x}; the mutation did not land"
        )
    logger.info(
        "CHK-STIMULUS-TOC-ENTRY: %s %s (payload is %s). %s. The field sits at flash "
        "0x%06x and the device must serve %s there. Every other TOC rule is left "
        "SATISFIED -- identifier PTOC, major_version %d, image_count inside "
        "0 < n <= %d, payload_length agreeing with the manifest, every image type "
        "known, every declared range inside the payload and matching its own digest "
        "-- so %s is the only rule validate_manifest_payload can refuse this slot on",
        slot, defect, "ENCRYPTED" if encrypted else "plaintext", detail,
        p + off, stored.hex(), pm.TOC_MAJOR_VERSION, pm.TOC_MAX_IMAGE_COUNT,
        DEFECT_TOKEN[defect].split(" idx=")[0],
    )
    return stored


def assert_served_entry_field(logger, flash, slot: str, defect: str,
                              expected: bytes, payload_offset: int) -> None:
    off, _size = FIELD[defect]
    # One SPI read must cover the field; the ROM fetches the payload in a single transfer.
    fd.assert_served_field(
        logger, flash, slot, payload_offset + off, expected,
        f"{slot} TOC {FIELD_NAME[defect]}",
    )
