# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the two ANNOUNCED per-image arms of the TOC loop.

THE PROBLEM THIS MODULE EXISTS TO SOLVE. ``validate_manifest_payload``
(``bootrom/prod/src/manifest_load.c``) walks the TOC entries and grades each one in
a fixed order. Four of those arms can refuse a well-formed-looking entry::

    is_known_image_type(e->type) fails -> MANIFEST_ERR_BAD_IMAGE_TYPE   (silent)
    end < off  or  end > p_len         -> MANIFEST_ERR_IMAGE_OOB        (SILENT)
    off < prev_end                     -> IMAGE_ORDER_BAD idx= + IMAGE_OVERLAP
    e->length == 0                     -> IMAGE_LEN_ZERO  idx= + IMAGE_OOB
    (len & 3) != 0                     -> IMAGE_LEN_ALIGN idx= + IMAGE_OOB

Unlike the header arms :mod:`sep_toc_defect` targets, the two arms here PRINT. That
changes what carries the attribution, and it has to, because the error code on its
own is not enough: the SILENT bounds arm returns exactly the same
``MANIFEST_ERR_IMAGE_OOB`` as the alignment arm below it. A row that overran the
payload would therefore show this family's error code while running a completely
different check. Three things carry the attribution instead, and every member
asserts all three:

  * THE TOKEN, INCLUDING ITS INDEX. ``simputshex32`` renders the entry index, so the
    console says ``IMAGE_ORDER_BAD idx=0x00000001`` or ``IMAGE_LEN_ALIGN
    idx=0x00000000`` -- which arm fired AND which entry it fired on. Each member
    requires its own token and FORBIDS its sibling's, so a row cannot pass on the
    other family's verdict;
  * THE ERROR CODE, ``0x0003000f`` for the ordering arm and ``0x0003000e`` for the
    alignment arm, with the sibling's code forbidden as well;
  * THE BYTES THE DEVICE SERVED. :func:`assert_served_entry_field` requires the
    flash BFM to have returned this testcase's exact planted bytes at the exact
    flash address of the mutated TOC-entry field. That is the half the ROM cannot
    fake.

Both arms also sit downstream of ``manifest_crypto_validate``, so the slot's
``SIG_VALID`` and (when encrypted) ``DECRYPT_OK`` must have been printed before the
rejection; the bases assert that ordering.

WHAT IS NOT COVERED, stated plainly. ``IMAGE_LEN_ZERO`` is the third announced arm
of the same loop and has no row in this batch; ``sep_bl1_size_invalid_test`` covers
the zero-length BL1 separately. The silent bounds and image-type arms are not
exercised here either -- they are forbidden, not planted. The ordering check's
OTHER half, an image starting before the TOC region, is likewise unexercised: both
ordering rows plant the violation between two images, which is the half a
two-image payload reaches.
"""

from __future__ import annotations

from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td

# The two packed images and the fuse preloads they need are the same artefacts the
# TOC-header family uses, and the reasoning for each is written down once, there.
PLAINTEXT_IMAGE = td.PLAINTEXT_IMAGE
ENCRYPTED_IMAGE = td.ENCRYPTED_IMAGE
PLAINTEXT_EFUSE = td.PLAINTEXT_EFUSE
ENCRYPTED_EFUSE = td.ENCRYPTED_EFUSE

# BOTH SLOTS OF EACH IMAGE SHARE ONE ENCRYPTION STATE, as for the header family;
# ``sep_toc_defect``'s module docstring sets out the consequences. A BACKUP cell
# is unaffected because its primary is refused on the manifest magic upstream of
# the first read of the encryption flag; a PRIMARY ENCRYPTED cell recovers onto a
# backup that is also encrypted, which is why those cells require the decryption
# markers twice.

# manifest.h
ERR_BAD_IMAGE_TYPE = 0x0003_000D
ERR_IMAGE_OOB = 0x0003_000E
ERR_IMAGE_OVERLAP = 0x0003_000F
ERR_IMAGE_HASH_MISMATCH = 0x0003_0019
# The failover trigger the backup family plants in its PRIMARY slot.
ERR_BAD_MAGIC = td.ERR_BAD_MAGIC

# The two defect families, named as the tracker names them.
ORDER = "images_out_of_order"
SIZE = "invalid_payload_image_size"

# ── The two stimuli ──────────────────────────────────────────────────────────
# IMAGE ORDER. Image 0 keeps the 0x1000 the shipped payload already gives its
# SEP_BL1, and image 1 declares 0x500 -- below image 0's start, so the ordering
# comparison against the previous image's end refuses it.
SECOND_IMAGE_OFFSET = 0x500
# The shipped payload declares ONE image, so entry 1 has to be created. Its body
# is a 256-byte slice of the BL1: 4-byte aligned and non-zero, so neither
# IMAGE_LEN_ZERO nor IMAGE_LEN_ALIGN can pre-empt the ordering check. Its type is
# SEPBL2. Entry 1's length is never read by the arm under test -- the ordering
# comparison precedes it -- so its value carries no verdict.
SECOND_IMAGE_LENGTH = 256
SECOND_IMAGE_TYPE = pm.IMAGE_TYPE_SEP_BL2
# The violating entry is index 1: entry 0 stays valid and ascending, and entry 1
# declares an offset below entry 0's end.
ORDER_ENTRY_INDEX = 1

# IMAGE LENGTH. Any length that is not a multiple of 4 violates ``(len & 3u) != 0``,
# but the declared image must still end inside the payload. The SILENT
# ``end > p_len`` arm runs BEFORE the alignment arm and returns the SAME
# ``MANIFEST_ERR_IMAGE_OOB``, so a length that overruns reports this family's error
# code while exercising the bounds check instead. ``pm.set_toc_entry_length``
# refuses such a value rather than planting it.
#
# 0x72D is the largest value that is 1 modulo 4 and still ends inside the payload
# on BOTH shipped images, so all four SIZE rows plant one identical value. The room
# is 1840 bytes on both, measured from image 0 at 0x1000. On the encrypted image
# the manifest's ``payload_length`` is 5952, but that counts the PKCS#7 block the
# packer appended; the plaintext the ROM parses after decryption is 5936, and
# ``set_toc_entry_length`` bounds against the smaller of the two so the declared
# image cannot run past the bytes that exist.
#
# RESIDUES 2 AND 3 ARE UNCOVERED. All four SIZE rows plant residue 1. A ROM that
# had written ``len & 1`` in place of ``len & 3`` would accept a length of 2 modulo
# 4 and is caught only by a row planting one.
BAD_IMAGE_LENGTH = 0x72D
SIZE_ENTRY_INDEX = 0

# ── Per-family descriptors ───────────────────────────────────────────────────
# Console token, rendered as simputshex32 prints it: message then 0x%08x.
DEFECT_TOKEN = {
    ORDER: f"IMAGE_ORDER_BAD idx=0x{ORDER_ENTRY_INDEX:08x}",
    SIZE: f"IMAGE_LEN_ALIGN idx=0x{SIZE_ENTRY_INDEX:08x}",
}
# The bare prefix as ``sep_toc_defect.OTHER_PAYLOAD_TOKENS`` spells it, so a family
# can remove its OWN token from that forbidden list and keep its sibling's.
_TOKEN_PREFIX = {ORDER: "IMAGE_ORDER_BAD", SIZE: "IMAGE_LEN_ALIGN"}
EXPECTED_ERROR = {ORDER: ERR_IMAGE_OVERLAP, SIZE: ERR_IMAGE_OOB}
# (payload-relative offset, width) of the mutated TOC-entry field, manifest.h.
FIELD = {
    ORDER: (pm.toc_entry_at(ORDER_ENTRY_INDEX) + pm.E_OFFSET, 8),
    SIZE: (pm.toc_entry_at(SIZE_ENTRY_INDEX) + pm.E_LENGTH, 8),
}
FIELD_NAME = {ORDER: "image 1 offset", SIZE: "image 0 length"}

# Decryption stage markers, manifest_crypto.c.
DECRYPT_START = td.DECRYPT_START
DECRYPT_OK = td.DECRYPT_OK

# Decryption failure tokens; forbidden on every member for the same reason as in
# the header family -- a plaintext row must not decrypt at all, and an encrypted
# row's decryption has to SUCCEED or the TOC loop is never reached.
DECRYPT_FAILURE_TOKENS = td.DECRYPT_FAILURE_TOKENS


def sibling_error(defect: str) -> int:
    """The error code of the OTHER entry arm in this batch.

    Every member forbids this, which is the direct answer to "would this testcase
    still pass if its mutation were replaced by its neighbour's?". It would not.
    """
    return EXPECTED_ERROR[SIZE if defect == ORDER else ORDER]


def other_payload_tokens(defect: str) -> tuple[str, ...]:
    """Every payload token except this family's own.

    Built from ``sep_toc_defect.OTHER_PAYLOAD_TOKENS`` so the two families share one
    list and neither can drift. Removing only this row's own prefix leaves the
    SIBLING's token forbidden, which is the console half of the swap test.
    """
    mine = _TOKEN_PREFIX[defect]
    if mine not in td.OTHER_PAYLOAD_TOKENS:
        raise AssertionError(
            f"{mine!r} is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so this "
            f"family's token would be neither required by one row nor forbidden by "
            f"its sibling; the swap-test defence has silently lapsed"
        )
    return tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != mine)


def neighbouring_errors(defect: str, *, exclude: tuple[int, ...] = ()) -> list[str]:
    """``MANIFEST_ERR=`` codes that would mean a different check ended the run.

    Covers the sibling entry arm, both arms of the TOC header family
    (``sep_toc_defect``), and the structural codes ahead of the payload checks. The
    image-type and hash codes matter most here: they are the two OTHER ways the same
    TOC loop can refuse an entry, and the image-type arm is silent.

    ``exclude`` drops a code a scenario legitimately produces elsewhere in the run.
    The backup family needs it for ``ERR_BAD_MAGIC``, which is the failover trigger
    planted in its PRIMARY slot and must therefore appear.
    """
    codes = (sibling_error(defect), ERR_BAD_IMAGE_TYPE, ERR_IMAGE_HASH_MISMATCH,
             td.ERR_BAD_MAGIC, td.ERR_BAD_VERSION, td.ERR_BAD_LENGTH,
             td.ERR_BAD_TOC_ID, td.ERR_BAD_TOC_VERSION, td.ERR_TOC_COUNT,
             td.ERR_PAYLOAD_TOO_LARGE, td.ERR_NO_BL1_IMAGE)
    return [f"MANIFEST_ERR=0x{c:08x}" for c in codes if c not in exclude]


def plant(logger, buf: bytearray, slot: str, defect: str) -> bytes:
    """Plant this batch's stimulus in ``slot``'s TOC entries and return the stored bytes.

    The return value is what the flash DEVICE must later be shown to have served.
    For a plaintext payload those are the planted little-endian bytes themselves;
    for an encrypted one they are the CIPHERTEXT the re-encryption produced, which
    is the only form the device ever holds. Asserting the stored form -- rather than
    a value the ROM echoed -- is what makes the evidence independent of the ROM's
    own account of the run.
    """
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
    """Require the device to have returned ``expected`` at the mutated field's address.

    ``fd.assert_served_field`` addresses relative to the manifest base, so the
    payload-relative offset is rebased here by the manifest's own
    ``boot_arguments.payload_offset``. The check is the cross-family discriminator:
    a run that planted a neighbouring cell's mutation would serve different bytes at
    this address, or the same bytes at a different one.

    THE ADDRESS IS IN THE PAYLOAD, NOT THE MANIFEST, which is a wider use than
    ``assert_served_field`` was written for -- its own note reasons about the single
    1184-byte manifest fetch. Its requirement still holds: the ROM stages the payload
    in one further transfer (``PAYLOAD_DST=``), so one read covers the field. If the
    transport ever splits that transfer, this fails loudly rather than silently
    checking the wrong bytes.
    """
    off, _size = FIELD[defect]
    fd.assert_served_field(
        logger, flash, slot, payload_offset + off, expected,
        f"{slot} TOC {FIELD_NAME[defect]}",
    )
