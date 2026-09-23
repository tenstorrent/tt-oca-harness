# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the two silent TOC header checks of the ROM.

Plants a bad TOC major version or image count and checks the error code, its place
after SIG_VALID/DECRYPT_OK, and the bytes the flash device served at that field.
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

# Both slots of an image share one encryption state.

_EFUSE_DIR = _DV_ROOT / "tb" / "efuse_preloads" / "efuse_configurations"
# LC=PROD, SBOOT_DIS=0, no class key: all a plaintext payload needs.
PLAINTEXT_EFUSE = _EFUSE_DIR / "sep_efuse_lc_prod.toml"
# Adds the CLASS_KEY for AES key derivation; without it the run fails at BAD_TOC_ID.
ENCRYPTED_EFUSE = _EFUSE_DIR / "sep_efuse_lc_prod_class_key.toml"

ERR_BAD_MAGIC = 0x0003_0002
ERR_BAD_VERSION = 0x0003_0003
ERR_BAD_LENGTH = 0x0003_0004
ERR_BAD_TOC_ID = 0x0003_0005
ERR_BAD_TOC_VERSION = 0x0003_0006
ERR_PAYLOAD_TOO_LARGE = 0x0003_0007
ERR_NO_BL1_IMAGE = 0x0003_0008
ERR_TOC_COUNT = 0x0003_0010

# Adjacent value above TOC_MAJOR_VERSION.
BAD_TOC_VERSION = pm.TOC_MAJOR_VERSION + 1

# One past the 256 limit.
BAD_IMAGE_COUNT = pm.TOC_MAX_IMAGE_COUNT + 1

# (payload-relative offset, width) of each mutated TOC header field.
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

DECRYPT_START = "DECRYPT_START"
DECRYPT_OK = "DECRYPT_OK"

# The arms under test print nothing, so every other payload token is forbidden.
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

# Plaintext rows must not decrypt, and encrypted rows must decrypt to reach the TOC arm.
DECRYPT_FAILURE_TOKENS = (
    "AES_INIT_FAIL", "AES_INIT_BUSY", "AES_DEC_FAIL", "AES_CTRL_REJECTED",
    "AES_ALERT_AFTER_DEC", "AES_ALERT_STATUS=", "KDF_FAIL", "KDF_HMAC_FAIL",
    "HMAC_ERR_CODE=", "HMAC_START_REJECTED", "HMAC_OP_REJECTED",
    "SHA_START_REJECTED", "SHA_OP_REJECTED",
)


def sibling_error(field: str) -> int:
    other = "image_count" if field == "version_major" else "version_major"
    return EXPECTED_ERROR[other]


def plant(logger, buf: bytearray, slot: str, field: str) -> bytes:
    if field not in FIELDS:
        raise ValueError(f"unknown TOC field {field!r}; expected one of {list(FIELDS)}")
    off, size = FIELDS[field]
    encrypted = pm.is_encrypted(buf, slot)
    was = MUTATOR[field](buf, slot, PLANTED[field])
    p = pm.payload_base(buf, slot)
    # For an encrypted slot this is ciphertext, the only form the flash device holds.
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
    off, _size = FIELDS[field]
    # One SPI read must cover the field; the ROM fetches the payload in a single transfer.
    fd.assert_served_field(
        logger, flash, buf_slot, payload_offset + off, expected,
        f"{buf_slot} TOC {field}",
    )
