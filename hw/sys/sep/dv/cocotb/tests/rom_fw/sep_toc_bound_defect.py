# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the TOC/manifest length agreement and the entry-0 bound.

THE PROBLEM THIS MODULE EXISTS TO SOLVE. Two rules of ``validate_manifest_payload``
(``bootrom/prod/src/manifest_load.c``) constrain how much payload a TOC may claim
and where an image body may sit. They fire in two DIFFERENT stages, and the stage
is what separates them::

    TOC HEADER stage, before any entry is read
      toc->payload_length disagrees with m->payload_length
                                  -> TOC_PLEN_MISMATCH= + MANIFEST_ERR_BAD_LENGTH
    PER-IMAGE loop, once per entry
      end < off / end > p_len     -> MANIFEST_ERR_IMAGE_OOB           (SILENT)
      off < prev_end              -> IMAGE_ORDER_BAD idx= + IMAGE_OVERLAP

Both arms here PRINT, so each row's token names the rule that fired. Three things
carry the attribution, and every member asserts all three:

  * THE TOKEN. ``TOC_PLEN_MISMATCH=`` for the length-agreement arm, and
    ``IMAGE_ORDER_BAD idx=0x00000000`` for the entry-0 bound -- ``simputshex32``
    renders the index, so the console says WHICH rule and WHICH entry. Each member
    requires its own token and forbids every other payload token, including its
    sibling's;
  * THE ERROR CODE, ``0x00030004`` for the agreement arm and ``0x0003000f`` for the
    bound arm, with the sibling's code forbidden as well;
  * THE BYTES THE DEVICE SERVED. :func:`assert_served_bound_field` requires the
    flash BFM to have returned this testcase's exact planted bytes at the exact
    flash ADDRESS of the mutated field in this testcase's own slot. That is the half
    the ROM cannot fake.

WHICH CHECK FIRES FIRST, PER ROW, AND WHY THE OTHER CANNOT. The agreement arm sits
above the per-image loop, so on a PLEN row the loop is never entered and no image
bound can be evaluated -- the entry is left exactly as shipped in any case. On a
BOUND row the TOC's ``payload_length`` is untouched and still equals the manifest's,
so the agreement arm cannot fire; the loop is then entered and entry 0's offset
trips ``off < prev_end``. The two stimuli are therefore not merely differently
announced, they are mutually unreachable. The mutators enforce that offline, before
anything is simulated: ``pm.set_toc_payload_length`` and ``pm.set_toc_entry_offset``
each reproduce the ROM's own rule and REFUSE any value the ROM would accept, and
``set_toc_entry_offset`` additionally refuses any value that would reach the silent
``end > p_len`` arm above the bound. A stimulus that did not violate the arm its row
names therefore raises at build time rather than producing a run to interpret.

HOW THIS FAMILY RELATES TO ``sep_toc_entry_defect``'s ORDERING ROW, stated plainly
because the two land on the SAME ``if``. ``off < prev_end`` enforces one rule with
two halves: an image must start after the TOC REGION, and after the PREVIOUS IMAGE.
``sep_toc_entry_defect`` plants entry 1 below entry 0's end, the previous-image
half, and its docstring records the TOC-region half as unexercised. This family is
that half: entry 0 alone, declaring a body that begins inside the TOC region the ROM
is still parsing. What separates the two rows on the console is the ENTRY INDEX the
token carries -- ``idx=0x00000000`` here against ``idx=0x00000001`` there -- and
every member of this family FORBIDS the neighbour's exact token. What separates them
off the console is the field address the device must have served -- entry 0's offset
field here, entry 1's there. Those two are the whole of the separation. The payloads
also differ in image count, 1 here against 2 there, but NOTHING ASSERTS IT: the count
appears only in a fixed log string, ``verify_sealed`` does not check it, and
``toc_entry_lower_bound`` reads it without constraining it. It is a true fact about
the artefacts and not a check, so it is not offered as a third separator. The ROM
does not report which HALF of the bound was violated, and no assertion here claims
it does.

WHAT IS NOT COVERED, stated plainly. The SILENT ``end > p_len`` and ``end < off``
arms are forbidden, not planted; the mutators refuse any value that would reach
them, precisely so a row cannot report this family's verdict from an unannounced
check. On the agreement arm, only the "TOC claims MORE than the manifest" direction
is planted; for an encrypted payload the other direction -- the manifest running
more than one AES block ahead of the TOC -- is a distinct sub-condition of the same
``if`` and has no row here. ``IMAGE_LEN_ZERO`` and ``IMAGE_LEN_ALIGN`` belong to
``sep_toc_entry_defect``.
"""

from __future__ import annotations

from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw import sep_toc_entry_defect as ted

# The two packed images and the fuse preloads they need are the same artefacts the
# other TOC families use, and the reasoning for each is written down once, there.
PLAINTEXT_IMAGE = td.PLAINTEXT_IMAGE
ENCRYPTED_IMAGE = td.ENCRYPTED_IMAGE
PLAINTEXT_EFUSE = td.PLAINTEXT_EFUSE
ENCRYPTED_EFUSE = td.ENCRYPTED_EFUSE

# BOTH SLOTS SHARE ONE ENCRYPTION STATE HERE, AND THE REFERENCE'S DO NOT. The
# consequences are identical to the other TOC families' and are set out in full in
# ``sep_toc_defect``'s module docstring: a BACKUP cell is unaffected because its
# primary is refused on the manifest magic upstream of the first read of the
# encryption flag, while a PRIMARY ENCRYPTED cell recovers onto an encrypted backup
# where the reference recovers onto a plaintext one -- more work for the DUT, and
# the reason those cells require the decryption markers twice.

# manifest.h
ERR_BAD_LENGTH = td.ERR_BAD_LENGTH
ERR_IMAGE_OOB = ted.ERR_IMAGE_OOB
ERR_IMAGE_OVERLAP = ted.ERR_IMAGE_OVERLAP
# The failover trigger the backup family plants in its PRIMARY slot.
ERR_BAD_MAGIC = td.ERR_BAD_MAGIC

# The two defect families, named as the tracker names them.
BOUND = "payload_image_exceeds_bound"
PLEN = "toc_payload_size_mismatch"

# ── The two stimuli ──────────────────────────────────────────────────────────
# IMAGE BOUND. The reference
# (``tb/cocotb_tests/sep_firmware_payload_validation_test.py``, the four
# ``*_PAYLOAD_IMAGE_EXCEEDS_BOUND`` branches at ``:637-659``) writes
# ``payload_images[0].offset = 0x100``. Its ROM
# (``firmware/bootcode/src/manifest.c:455-459``) returns ``SEP_MSG_IMAGE_EXCEEDS_BOUND``
# for ``image->offset < prev_end_offset`` -- the SAME rule this ROM enforces as
# ``off < prev_end``. The reference's separate ``SEP_MSG_IMAGE_EXCEEDS_PAYLOAD_LENGTH``
# (``:462-465``) covers the payload-length bound, so this family's name is about the
# TOC-region bound and not about running off the end of the payload.
#
# 0x100 CANNOT BE PLANTED HERE, AND PLANTING IT WOULD NOT VIOLATE ANYTHING. The
# bound is the TOC region, whose size follows the image count: the reference's
# payload declares TWO images, so its region is 32 + 2*216 = 464 bytes and 0x100=256
# falls inside it. The shipped OSS payload declares ONE image, so its region is
# 32 + 216 = 248 bytes and 256 is ABOVE the bound -- the ROM would ACCEPT the
# ordering of that entry and the row would prove nothing.
# ``pm.set_toc_entry_offset`` refuses such a value rather than planting it.
#
# 240 is the largest 8-byte-aligned offset still inside the 248-byte region, so it
# is the TIGHTEST possible violation: it pins the comparison to exactly the TOC
# region size rather than to some looser bound a mistake might have used. The
# 8-byte alignment is the reference's own property -- its ROM refuses an unaligned
# offset before reaching the bound, and 0x100 satisfies it. THIS ROM HAS NO SUCH
# CHECK, recorded as ``FINDINGS[0918rtl] R03``; keeping the planted offset aligned
# is what stops these rows from straying onto that missing arm in either direction.
BOUND_IMAGE_OFFSET = 240
BOUND_ENTRY_INDEX = 0

# TOC PAYLOAD LENGTH. The reference plants ``toc.payload_length = 0x2000``
# (``sep_firmware_payload_validation_test.py:661-684``, all four branches). THIS
# VALUE IS PLANTED VERBATIM: 8192 exceeds the shipped payload's 5936 plaintext
# bytes, so it violates the plaintext rule (``!=``) and the encrypted rule
# (``toc_p_len > m->payload_length``, where the manifest declares 5952) alike.
#
# THE OTHER DIRECTION IS UNCOVERED, BATCH-WIDE. The encrypted arm is an ``||`` of
# two sub-conditions, and 0x2000 only ever reaches the first. A TOC claiming LESS
# than the manifest by more than one AES block -- the sub-condition that bounds the
# PKCS#7 slack -- is caught only by a row planting a value below the manifest's, and
# all four PLEN cells plant the same above-manifest value.
BAD_TOC_PAYLOAD_LENGTH = 0x2000

# ── Per-family descriptors ───────────────────────────────────────────────────
# Console token, rendered as the ROM prints it.
DEFECT_TOKEN = {
    BOUND: f"IMAGE_ORDER_BAD idx=0x{BOUND_ENTRY_INDEX:08x}",
    PLEN: "TOC_PLEN_MISMATCH=",
}
# The bare prefix as ``sep_toc_defect.OTHER_PAYLOAD_TOKENS`` spells it, so a family
# can remove its OWN token from that forbidden list and keep every other.
_TOKEN_PREFIX = {BOUND: "IMAGE_ORDER_BAD", PLEN: "TOC_PLEN_MISMATCH="}
EXPECTED_ERROR = {BOUND: ERR_IMAGE_OVERLAP, PLEN: ERR_BAD_LENGTH}
# (payload-relative offset, width) of the mutated field, manifest.h.
FIELD = {
    BOUND: (pm.toc_entry_at(BOUND_ENTRY_INDEX) + pm.E_OFFSET, 8),
    PLEN: (pm.TOC_OFF_PAYLOAD_LENGTH, 8),
}
FIELD_NAME = {BOUND: "image 0 offset", PLEN: "TOC payload_length"}

# The neighbouring family's EXACT token, forbidden by every member of this one.
# ``sep_toc_entry_defect``'s ordering row lands on the same ``if`` as BOUND and
# prints the same prefix, differing only in the entry index, so forbidding the bare
# prefix is not available to BOUND and this exact string is what stands in for it.
FOREIGN_TOKENS = {
    BOUND: (ted.DEFECT_TOKEN[ted.ORDER],),
    PLEN: (),
}

# Decryption stage markers, manifest_crypto.c.
DECRYPT_START = td.DECRYPT_START
DECRYPT_OK = td.DECRYPT_OK

# Decryption failure tokens; forbidden on every member for the same reason as in
# the other TOC families -- a plaintext row must not decrypt at all, and an
# encrypted row's decryption has to SUCCEED or the arm under test is never reached.
DECRYPT_FAILURE_TOKENS = td.DECRYPT_FAILURE_TOKENS


def sibling_error(defect: str) -> int:
    """The error code of the OTHER arm in this batch.

    Every member forbids this, which is the direct answer to "would this testcase
    still pass if its mutation were replaced by its neighbour's?". It would not.
    """
    return EXPECTED_ERROR[PLEN if defect == BOUND else BOUND]


def other_payload_tokens(defect: str) -> tuple[str, ...]:
    """Every payload token except this family's own, plus the neighbour's exact token.

    Built from ``sep_toc_defect.OTHER_PAYLOAD_TOKENS`` so all four TOC families share
    one list and none can drift. Removing only this row's own prefix leaves the
    sibling's token forbidden, which is the console half of the swap test.
    """
    mine = _TOKEN_PREFIX[defect]
    if mine not in td.OTHER_PAYLOAD_TOKENS:
        raise AssertionError(
            f"{mine!r} is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so this "
            f"family's token would be neither required by one row nor forbidden by "
            f"its sibling; the swap-test defence has silently lapsed"
        )
    return tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != mine) + FOREIGN_TOKENS[defect]


def neighbouring_errors(defect: str, *, exclude: tuple[int, ...] = ()) -> list[str]:
    """``MANIFEST_ERR=`` codes that would mean a different check ended the run.

    Covers the sibling arm, both per-image arms of ``sep_toc_entry_defect``, both
    header arms of ``sep_toc_defect``, and the structural codes ahead of the payload
    checks. ``MANIFEST_ERR_IMAGE_OOB`` matters most to the BOUND rows: it is what the
    two SILENT arms immediately above the bound return, so forbidding it is what says
    the offset was refused by the arm that ANNOUNCED itself.

    This family's own expected code is removed, which is why the list is built here
    rather than taken from ``sep_toc_entry_defect``: the PLEN arm's verdict IS
    ``MANIFEST_ERR_BAD_LENGTH``, a code every other TOC family forbids.

    ``exclude`` drops a code a scenario legitimately produces elsewhere in the run.
    The backup family needs it for ``ERR_BAD_MAGIC``, which is the failover trigger
    planted in its PRIMARY slot and must therefore appear.
    """
    codes = (sibling_error(defect), ERR_IMAGE_OOB, ted.ERR_BAD_IMAGE_TYPE,
             ted.ERR_IMAGE_HASH_MISMATCH, td.ERR_BAD_MAGIC, td.ERR_BAD_VERSION,
             td.ERR_BAD_LENGTH, td.ERR_BAD_TOC_ID, td.ERR_BAD_TOC_VERSION,
             td.ERR_TOC_COUNT, td.ERR_PAYLOAD_TOO_LARGE, td.ERR_NO_BL1_IMAGE)
    drop = set(exclude) | {EXPECTED_ERROR[defect]}
    return [f"MANIFEST_ERR=0x{c:08x}" for c in codes if c not in drop]


def plant(logger, buf: bytearray, slot: str, defect: str) -> bytes:
    """Plant this batch's stimulus in ``slot``'s TOC and return the stored bytes.

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
    p_len = pm.manifest_payload_length(buf, slot)

    if defect == BOUND:
        bound = pm.toc_entry_lower_bound(buf, slot, BOUND_ENTRY_INDEX)
        was = pm.set_toc_entry_offset(buf, slot, BOUND_ENTRY_INDEX,
                                      BOUND_IMAGE_OFFSET)
        detail = (f"image {BOUND_ENTRY_INDEX} offset 0x{was:x} -> "
                  f"0x{BOUND_IMAGE_OFFSET:x}, which is BELOW the {bound}-byte TOC "
                  f"region the ROM seeds prev_end with, so the declared body would "
                  f"begin inside the metadata being parsed; its digest was "
                  f"recomputed over the newly declared range")
        expect = BOUND_IMAGE_OFFSET
    else:
        was = pm.set_toc_payload_length(buf, slot, BAD_TOC_PAYLOAD_LENGTH)
        detail = (f"TOC payload_length {was} -> {BAD_TOC_PAYLOAD_LENGTH}, against "
                  f"the manifest's {p_len}; the TOC claims "
                  f"{BAD_TOC_PAYLOAD_LENGTH - p_len} bytes MORE than were loaded")
        expect = BAD_TOC_PAYLOAD_LENGTH

    p = pm.payload_base(buf, slot)
    stored = bytes(buf[p + off:p + off + size])
    now = int.from_bytes(bytes(pm.toc_plaintext(buf, slot)[off:off + size]), "little")
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
        slot, defect, "ENCRYPTED" if encrypted else "plaintext", detail,
        p + off, stored.hex(), pm.TOC_MAJOR_VERSION, pm.TOC_MAX_IMAGE_COUNT,
        DEFECT_TOKEN[defect].rstrip("=").split(" idx=")[0],
    )
    return stored


def assert_served_bound_field(logger, flash, slot: str, defect: str,
                              expected: bytes, payload_offset: int) -> None:
    """Require the device to have returned ``expected`` at the mutated field's address.

    ``fd.assert_served_field`` addresses relative to the manifest base, so the
    payload-relative offset is rebased here by the manifest's own
    ``boot_arguments.payload_offset``. The check is the cross-family discriminator:
    a run that planted a neighbouring cell's mutation would serve different bytes at
    this address, or the same bytes at a different one.

    THE ADDRESS DOES THE WORK THE CIPHERTEXT CANNOT, on the encrypted members. CBC
    makes block ``k`` depend only on plaintext blocks ``0..k``, and both fields this
    family mutates sit early -- the TOC payload_length in block 0, entry 0's offset
    in block 2. The two slots' payloads are identical for far longer than that: on
    ``encrypted_boot.bin`` the BL1 bodies, entry 0's digest and every numeric TOC
    field are byte-for-byte the same in both slots, and the first difference is at
    payload byte 137, inside entry 0's trailing descriptor text, so the stored
    ciphertext first diverges at block 8. Both of this family's fields therefore
    serve IDENTICAL ciphertext in either slot, and only the flash address
    (``0x002xxx`` against ``0x042xxx``) says which slot was mutated. That address is
    exactly what this check pins.

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
        f"{slot} {FIELD_NAME[defect]}",
    )
