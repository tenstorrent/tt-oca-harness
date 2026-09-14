# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the two SILENT arms of ``validate_manifest_payload``.

THE PROBLEM THIS MODULE EXISTS TO SOLVE. ``validate_manifest_payload``
(``bootrom/prod/src/manifest_load.c``) grades the decrypted TOC in a fixed order,
and its first three arms behave differently on the console::

    toc->identifier  != TOC_HEADER_MAGIC_WORD -> MANIFEST_ERR_BAD_TOC_ID       (silent)
    toc->major_version != TOC_MAJOR_VERSION   -> MANIFEST_ERR_BAD_TOC_VERSION  (silent)
    n == 0 || n > 256                         -> MANIFEST_ERR_TOC_COUNT        (silent)
    toc_bytes > p_len                         -> TOC_REGION_OOB= + PAYLOAD_TOO_LARGE
    toc payload_length disagrees              -> TOC_PLEN_MISMATCH= + BAD_LENGTH

The two arms these testcases target print NOTHING of their own, so unlike a
``PAYLOAD_HASHED_LEN_BAD=`` row there is no token naming which check complained.
Three things carry the attribution instead, and every member asserts all three:

  * THE ERROR CODE, which differs between the two arms -- ``0x00030006`` for the
    version and ``0x00030010`` for the count. Each member additionally FORBIDS its
    sibling's code, so a row cannot pass on the other family's verdict;
  * THE PLACE IN THE CHAIN. Both arms sit downstream of ``manifest_crypto_validate``,
    so the slot's ``SIG_VALID`` and (when encrypted) ``DECRYPT_OK`` must have been
    printed before the rejection. An upstream rejection cannot produce that order;
  * THE BYTES THE DEVICE SERVED. :func:`assert_served_toc_field` requires the flash
    BFM to have returned this testcase's exact planted bytes at the exact flash
    address of the field. That is the half the ROM cannot fake, and it is what
    separates two rows whose consoles would otherwise be identical.

WHAT IS NOT COVERED, stated plainly. ``MANIFEST_ERR_BAD_TOC_ID`` is the arm above
both of these and has its own testcase
(``sep_decryption_failure_terminal_test``). The ``n == 0`` half of the image-count
check is not exercised here; see :data:`BAD_IMAGE_COUNT`.
"""

from __future__ import annotations

from pathlib import Path

from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd

_SEP_ROOT = Path(__file__).resolve().parents[4]
_DV_ROOT = Path(__file__).resolve().parents[3]

# The plaintext, signed image: BOTH slots carry encrypted_payload = 0.
PLAINTEXT_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "secure_boot.bin")
# The signed AND encrypted image: BOTH slots carry encrypted_payload = 1.
ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "encrypted_boot.bin")

# BOTH SLOTS SHARE ONE ENCRYPTION STATE HERE, AND THE REFERENCE'S DO NOT. Each
# of these images is packed from one config with a single setting applied to both
# slots, while a reference scenario sets the flag per slot and lets the other
# inherit the packer default -- primary 1, backup 0
# (``firmware/utils/pack_images/configs/default_test.yaml:46`` and ``:145``). So
# in every cell of this batch the slot NOT under test carries this image's
# encryption state rather than the reference's. Where that matters, and where it
# does not:
#
#   * a BACKUP cell is unaffected. Its primary is refused on the manifest magic
#     inside ``validate_manifest_header``, upstream of the point where
#     ``try_manifest_slot`` first reads the encryption flag, so the primary's
#     encryption state is unobservable in the run;
#   * a PRIMARY ENCRYPTED cell genuinely differs. The reference recovers onto a
#     PLAINTEXT backup; here the recovering backup is encrypted and decrypts too.
#     That is more work for the DUT, not less, and it is why those cells require
#     the decryption markers TWICE rather than once -- but the reference's
#     encrypted-primary / plaintext-backup mix is not reproduced.
#
# Closing the gap would need a third packed image with per-slot encryption. That
# is a packer-config change outside this batch.

_EFUSE_DIR = _DV_ROOT / "tb" / "efuse_preloads" / "efuse_configurations"
# LC=PROD, SBOOT_DIS=0, no class key: all a plaintext payload needs.
PLAINTEXT_EFUSE = _EFUSE_DIR / "sep_efuse_lc_prod.toml"
# The same, plus the CLASS_KEY the ROM's KBKDF derives the AES key from. Without
# it an encrypted payload decrypts to garbage and the run dies at BAD_TOC_ID
# instead of at the arm under test.
ENCRYPTED_EFUSE = _EFUSE_DIR / "sep_efuse_lc_prod_class_key.toml"

# manifest.h
ERR_BAD_MAGIC = 0x0003_0002
ERR_BAD_VERSION = 0x0003_0003
ERR_BAD_LENGTH = 0x0003_0004
ERR_BAD_TOC_ID = 0x0003_0005
ERR_BAD_TOC_VERSION = 0x0003_0006
ERR_PAYLOAD_TOO_LARGE = 0x0003_0007
ERR_NO_BL1_IMAGE = 0x0003_0008
ERR_TOC_COUNT = 0x0003_0010

# ── The two stimuli ──────────────────────────────────────────────────────────
# TOC major version. The reference draws uniformly from every value in 0..10 that
# is not TOC_MAJOR_VERSION
# (``tb/cocotb_tests/sep_firmware_payload_validation_test.py``
# ``_generate_invalid_toc_version_major``), so any member of that set is a
# faithful reduction of the draw. TOC_MAJOR_VERSION + 1 is chosen because it is
# the ADJACENT value: a ROM that had written ``<`` instead of ``!=`` -- accepting
# any newer TOC -- would pass a draw of 0 and is caught only by a draw above the
# valid version. A single run can pin one side of the comparison, and this is the
# side a forward-compatible-looking mistake lands on.
#
# THE OTHER SIDE IS UNCOVERED, BATCH-WIDE. The symmetric mistake -- ``>`` in
# place of ``!=``, accepting any OLDER TOC -- is caught only by a draw BELOW the
# valid version, and all four TOC-version cells plant the same above-valid value.
# A row planting 0 would close it; ``set_toc_version_major`` already accepts one.
BAD_TOC_VERSION = pm.TOC_MAJOR_VERSION + 1

# TOC image count. The reference draws from ``[0, 257]``
# (``sep_firmware_payload_validation_test.py``, the four
# ``*_INVALID_PAYLOAD_IMAGE_COUNT`` branches); both land on the same
# ``MANIFEST_ERR_TOC_COUNT`` arm. 257 is chosen for the same boundary reason as
# above: it is exactly one past ``n > 256``, so it pins the constant, whereas 0
# only distinguishes itself from 1. THE ``n == 0`` HALF OF THIS CHECK IS
# THEREFORE NOT EXERCISED BY THIS BATCH -- it is the other arm of the same ``if``
# and would need its own row.
BAD_IMAGE_COUNT = pm.TOC_MAX_IMAGE_COUNT + 1

# ── Field descriptors ────────────────────────────────────────────────────────
# (payload-relative offset, width) of each mutated TOC header field, manifest.h.
FIELDS = {
    "version_major": (pm.TOC_OFF_MAJOR_VERSION, 2),
    "image_count": (pm.TOC_OFF_IMAGE_COUNT, 8),
}
PLANTED = {
    "version_major": BAD_TOC_VERSION,
    "image_count": BAD_IMAGE_COUNT,
}
EXPECTED_ERROR = {
    "version_major": ERR_BAD_TOC_VERSION,
    "image_count": ERR_TOC_COUNT,
}
MUTATOR = {
    "version_major": pm.set_toc_version_major,
    "image_count": pm.set_toc_image_count,
}

# Decryption stage markers, manifest_crypto.c.
DECRYPT_START = "DECRYPT_START"
DECRYPT_OK = "DECRYPT_OK"

# Every OTHER token validate_manifest_payload and its neighbours can print. The
# arms under test are silent, so forbidding all of these is what says the slot was
# refused by the arm this row names rather than by one that would have announced
# itself. TOC_REGION_OOB= matters most: it is the check IMMEDIATELY after the image
# count, and an image_count stimulus that slipped past the count bound would land
# there.
OTHER_PAYLOAD_TOKENS = (
    "TOC_REGION_OOB=", "TOC_PLEN_MISMATCH=", "IMAGE_ORDER_BAD", "IMAGE_LEN_ZERO",
    "IMAGE_LEN_ALIGN", "IMAGE_HASH_MISMATCH", "IMAGE_HASH_TIMEOUT",
    "NO_BL1_IMAGE", "BL1_ADDR_RANGE", "BL1_ENTRY_RANGE",
    "PAYLOAD_HASHED_LEN_BAD=", "ENC_HASHED_LEN_PARTIAL", "ENC_WITHOUT_SBOOT",
    "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE", "PAYLOAD_LEN_RANGE",
    "PAYLOAD_OVERLAPS_MANIFEST", "PAYLOAD_LOC_OVERFLOW", "PAYLOAD_NO_ROOM=",
    "MANIFEST_HASH_MISMATCH", "PLD_HASH_MISMATCH", "PLD_HASH_FAIL=",
    "RSA_VERIFY_FAIL", "SBOOT_OFF",
    fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
)

# Decryption failure tokens, aes_driver.c / manifest_crypto.c. Forbidden on every
# member: on a plaintext row nothing may decrypt at all, and on an encrypted row
# the decryption has to SUCCEED or the TOC arm under test is never reached.
DECRYPT_FAILURE_TOKENS = (
    "AES_INIT_FAIL", "AES_INIT_BUSY", "AES_DEC_FAIL", "AES_CTRL_REJECTED",
    "AES_ALERT_AFTER_DEC", "AES_ALERT_STATUS=", "KDF_FAIL", "KDF_HMAC_FAIL",
    "HMAC_ERR_CODE=", "HMAC_START_REJECTED", "HMAC_OP_REJECTED",
    "SHA_START_REJECTED", "SHA_OP_REJECTED",
)


def sibling_error(field: str) -> int:
    """The error code of the OTHER TOC arm in this batch.

    Every member forbids this, which is the direct answer to "would this testcase
    still pass if its mutation were replaced by its neighbour's?". It would not:
    a version stimulus that somehow produced TOC_COUNT, or the reverse, is refused
    here rather than accepted as a generic TOC rejection.
    """
    other = "image_count" if field == "version_major" else "version_major"
    return EXPECTED_ERROR[other]


def plant(logger, buf: bytearray, slot: str, field: str) -> bytes:
    """Plant this batch's stimulus in ``slot``'s TOC and return the stored bytes.

    The return value is what the flash DEVICE must later be shown to have served.
    For a plaintext payload those are the planted little-endian bytes themselves;
    for an encrypted one they are the CIPHERTEXT the re-encryption produced, which
    is the only form the device ever holds. Asserting the stored form -- rather
    than a value the ROM echoed -- is what makes the evidence independent of the
    ROM's own account of the run.
    """
    if field not in FIELDS:
        raise ValueError(f"unknown TOC field {field!r}; expected one of {list(FIELDS)}")
    off, size = FIELDS[field]
    encrypted = pm.is_encrypted(buf, slot)
    was = MUTATOR[field](buf, slot, PLANTED[field])
    p = pm.payload_base(buf, slot)
    stored = bytes(buf[p + off:p + off + size])
    now = int.from_bytes(bytes(pm.toc_plaintext(buf, slot)[off:off + size]), "little")
    assert now == PLANTED[field], (
        f"{slot} TOC {field} reads {now} after the write, expected "
        f"{PLANTED[field]}; the mutation did not land"
    )
    logger.info(
        "CHK-STIMULUS-TOC: %s TOC %s %d -> %d (payload is %s). The field sits at "
        "flash 0x%06x and the device must serve %s there. Every other TOC field is "
        "left VALID -- identifier PTOC, payload_length agreeing with the manifest, "
        "one in-bounds SEP_BL1 image -- so %s is the only rule "
        "validate_manifest_payload can refuse this slot on",
        slot, field, was, now, "ENCRYPTED" if encrypted else "plaintext",
        p + off, stored.hex(), field,
    )
    return stored


def assert_served_toc_field(logger, flash, buf_slot: str, field: str,
                            expected: bytes, payload_offset: int) -> None:
    """Require the device to have returned ``expected`` at the TOC field's address.

    ``fd.assert_served_field`` addresses relative to the manifest base, so the
    payload-relative offset is rebased here by the manifest's own
    ``boot_arguments.payload_offset``. The check is the cross-family discriminator:
    a run that planted a neighbouring cell's mutation would serve different bytes
    at this address, or the same bytes at a different one.

    THE ADDRESS IS IN THE PAYLOAD, NOT THE MANIFEST, which is a wider use than
    ``assert_served_field`` was written for -- its own note reasons about the
    single 1184-byte manifest fetch. Its requirement still holds: the ROM stages
    the payload in one further transfer (``PAYLOAD_DST=``), so one read covers the
    field. If the transport ever splits that transfer, this fails loudly rather
    than silently checking the wrong bytes.
    """
    off, _size = FIELDS[field]
    fd.assert_served_field(
        logger, flash, buf_slot, payload_offset + off, expected,
        f"{buf_slot} TOC {field}",
    )
