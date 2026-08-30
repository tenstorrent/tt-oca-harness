# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Targeted mutation of a packed SEP boot manifest, for negative boot testcases.

Mutating the packed bytes here rather than in a build step keeps these testcases
Python-only: no new firmware profile and no HDL rebuild.

LAYOUT AND THE TBS BOUNDARY. From ``bootrom/prod/include/manifest.h:198-234``, a
manifest is 1184 bytes::

    [0   .. 743]   TBS (to-be-signed)
    [744 .. 1127]  signature (384 B, RSA-3072 over manifest_hash)
    [1128.. 1159]  manifest_hash (32 B, SHA-256 of the TBS)
    [1160.. 1183]  boot_arguments (24 B)

That boundary decides what a mutation costs, and :func:`verify_layout` checks it
against the shipped image rather than trusting it:

  * A field OUTSIDE the TBS (``signature``, ``flag_args``) is written directly --
    the hash covers only the TBS, and the signature only the hash.
  * A field INSIDE the TBS invalidates ``manifest_hash``, so :func:`rehash` must
    follow. Re-signing is not needed and deliberately not done: the ROM checks the
    hash, then security_version, then signature_type, then public_key_sel, and only
    then the signature (``manifest_load.c:296-340`` then
    ``manifest_crypto.c:325-358``), so every in-TBS mutation used here is rejected
    before the RSA step and the stale signature is never reached. A mutation that
    must survive PAST RSA verification needs the private key instead.

SLOT ERASURE (:func:`erase_slot`) is a different stimulus: "nothing is at this
flash address", not "a manifest with one bad field". This ROM has no SPI device
probe -- ``ot_spi_init`` only writes CSRs and polls ``STATUS.READY``
(``src/sep_ot_spi.c:166-179``) -- so its only presence test is the manifest magic
(``src/manifest_load.c:130-131``). An erased slot is therefore indistinguishable
from an absent device: the BFM's backing store and its out-of-range reads are both
0xFF (``hw/common/dv/vip/ocah_spi_vip/cocotb/ocah_spi_flash.py:186,494-495``), and
a pulled-high MISO samples the same. Erasing rather than corrupting is what lets a
testcase assert the device returned all-0xFF, i.e. that the address was blank.
"""

from __future__ import annotations

import hashlib
import struct

# bootrom/prod/include/manifest.h:27-28
PRIMARY_MANIFEST_OFFSET = 0x1000
BACKUP_MANIFEST_OFFSET = 0x41000

MANIFEST_SIZE = 1184
# Length of the signed/hashed region: everything before the signature field.
TBS_LEN = 744

# Field offsets within a manifest, from manifest.h:198-234 and its sub-structs.
#
# Only offsets an actual mutator uses are defined here. verify_layout() cross-checks
# just OFF_IDENTIFIER and OFF_MANIFEST_HASH against a real image, so an unused
# offset would be an unverified number that reads as authoritative. Anyone adding
# one (e.g. the encryption fields) must extend verify_layout() to check it.
OFF_IDENTIFIER = 0        # uint32  "TBL1"
OFF_SECURITY_VERSION = 162  # uint16
OFF_SIGNATURE_TYPE = 165    # uint8
OFF_PUBLIC_KEY_SEL = 166    # uint16 {index:4, selection:3, rsvd:9}
OFF_PUBLIC_KEY = 168      # 384 B  -- RSA-3072 modulus, inside the TBS
OFF_SIGNATURE = 744       # 384 B  -- outside the TBS
OFF_MANIFEST_HASH = 1128  # 32 B   -- outside the TBS
OFF_FLAG_ARGS = 1168      # uint32 -- outside the TBS

PUBLIC_KEY_LEN = 384  # manifest.h:102, RSA_3072_KEY_SZ_BYTES

MANIFEST_MAGIC = b"TBL1"

# SHA-256 of the dev0 RSA-3072 modulus, copied verbatim from ROM key slot 0
# (bootrom/prod/src/key_digests.c:19-21). It is what check_pubkey_hash() compares
# a ROM-slot-0 manifest's modulus against, so it doubles as the cross-check that
# OFF_PUBLIC_KEY really points at the modulus -- see verify_public_key().
ROM_KEY0_DIGEST = bytes.fromhex(
    "4676d023736b5ebd5131f75b062a355e9ae1790e80c872b5ee9b0c1fff04c3e3"
)

# Erased-flash byte. Matches the BFM's backing store and its out-of-range read
# value (ocah_spi_flash.py:186,494-495), so an erased region in the image and an
# address past the end of the image are indistinguishable to the ROM -- which is
# what makes 0xFF the honest representation of "nothing is programmed here".
ERASED_BYTE = 0xFF

# manifest.h:88-90
FLAG_ARGS_BIT_SECURE_BOOT = 30


def slot_base(slot: str) -> int:
    """Flash byte offset of a manifest slot."""
    if slot == "primary":
        return PRIMARY_MANIFEST_OFFSET
    if slot == "backup":
        return BACKUP_MANIFEST_OFFSET
    raise ValueError(f"slot must be 'primary' or 'backup', got {slot!r}")


def slot_span(image: bytes | int, slot: str) -> tuple[int, int]:
    """``(start, end)`` flash byte range this packed image devotes to ``slot``.

    The primary slot runs from its manifest up to the backup manifest; the backup
    slot runs from its manifest to the end of the image. Derived from the image
    rather than hardcoded, because a slot's payload lives at a manifest-relative
    offset (``manifest_load.c:484`` computes ``src_addr + payload_offset``), so the
    span -- not just the 1184-byte header -- is what "this address holds a bootable
    slot" means.

    ``image`` may be the buffer or just its length. The length form exists so
    callers that only know the size (the transaction-evidence helpers) need not
    fabricate a quarter-megabyte throwaway buffer to ask this question.
    """
    start = slot_base(slot)
    image_len = image if isinstance(image, int) else len(image)
    if slot == "primary":
        end = BACKUP_MANIFEST_OFFSET
    else:
        end = image_len
    if end < start + MANIFEST_SIZE:
        raise AssertionError(
            f"image is too small to contain the {slot} slot: span "
            f"0x{start:x}..0x{end:x} is under {MANIFEST_SIZE} bytes. Either the "
            f"image is truncated or the slot offsets no longer match the packer"
        )
    return start, end


def erase_slot(buf: bytearray, slot: str) -> tuple[int, int]:
    """Fill a slot's whole flash span with 0xFF, i.e. make the address read blank.

    The "address not detected" stimulus; see the module docstring for why erasure
    rather than field corruption. Returns the erased ``(start, end)``.

    The layout is verified BEFORE erasing, which is the point: it proves a valid
    manifest really was at this address, so the test is removing a working slot
    rather than quietly erasing empty space and asserting on a no-op.
    """
    verify_layout(buf, slot)
    start, end = slot_span(buf, slot)
    buf[start:end] = bytes([ERASED_BYTE]) * (end - start)
    return start, end


def slot_is_erased(buf: bytes, slot: str) -> bool:
    """True iff every byte of the slot's span reads as the erased value."""
    start, end = slot_span(buf, slot)
    return all(b == ERASED_BYTE for b in bytes(buf[start:end]))


def tbs_hash(buf: bytes, base: int) -> bytes:
    """SHA-256 over the manifest's TBS region."""
    return hashlib.sha256(bytes(buf[base:base + TBS_LEN])).digest()


def verify_layout(buf: bytes, slot: str) -> None:
    """Assert the packed image matches the layout this module assumes.

    Called by every mutation entry point. Without it, a packer change (a moved
    field, a different TBS boundary) would turn every mutation below into a write
    into the wrong bytes -- and because these are negative tests, the ROM would
    still reject the image and the test would still look like it passed for the
    stated reason. This converts that silent-wrong-reason failure into a loud one.
    """
    base = slot_base(slot)
    ident = bytes(buf[base + OFF_IDENTIFIER:base + OFF_IDENTIFIER + 4])
    if ident != MANIFEST_MAGIC:
        raise AssertionError(
            f"{slot} manifest at 0x{base:x} does not start with {MANIFEST_MAGIC!r} "
            f"(got {ident!r}); the image is not the packed layout this expects"
        )
    stored = bytes(buf[base + OFF_MANIFEST_HASH:base + OFF_MANIFEST_HASH + 32])
    calc = tbs_hash(buf, base)
    if stored != calc:
        raise AssertionError(
            f"{slot} manifest_hash does not equal sha256(TBS[0:{TBS_LEN}]) "
            f"(stored {stored.hex()}, computed {calc.hex()}); the TBS boundary or "
            f"the hash field offset in sep_manifest_mutate no longer matches the packer"
        )


def rehash(buf: bytearray, slot: str) -> None:
    """Recompute ``manifest_hash`` after an in-TBS mutation."""
    base = slot_base(slot)
    buf[base + OFF_MANIFEST_HASH:base + OFF_MANIFEST_HASH + 32] = tbs_hash(buf, base)


def set_identifier(buf: bytearray, slot: str, value: bytes = b"\x99\x99\x99\x99") -> None:
    """Break the manifest magic, so the slot is rejected as BAD_MAGIC.

    The standard way to force a primary->backup failover.
    """
    verify_layout(buf, slot)
    base = slot_base(slot)
    if len(value) != 4:
        raise ValueError("identifier is 4 bytes")
    if value == MANIFEST_MAGIC:
        raise ValueError("value equals the valid magic; that is not a mutation")
    buf[base + OFF_IDENTIFIER:base + OFF_IDENTIFIER + 4] = value
    rehash(buf, slot)


def set_security_version(buf: bytearray, slot: str, value: int) -> None:
    """Set ``security_version`` (in-TBS; re-hashed).

    Rejected by ``check_security_version`` as VERSION_ROLLBACK when it is below
    the BL1_VERSION fuse's thermometer count, which happens before the signature
    is verified -- so the stale signature is never reached.
    """
    verify_layout(buf, slot)
    base = slot_base(slot)
    struct.pack_into("<H", buf, base + OFF_SECURITY_VERSION, value & 0xFFFF)
    rehash(buf, slot)


def set_public_key_sel(buf: bytearray, slot: str, *, selection: int, index: int = 0) -> None:
    """Set ``public_key_sel`` (in-TBS; re-hashed).

    ``{index:4, selection:3}`` per manifest.h:120-126. A ``selection`` of 3, 6 or
    7 is unassigned and must be rejected as BAD_KEY_SEL; an ``index`` at or above
    PUBK_SEL_NUM_ROM_KEYS (6) must be rejected as BAD_KEY_IDX. Both verdicts are
    reached before the RSA step.
    """
    verify_layout(buf, slot)
    base = slot_base(slot)
    value = (index & 0xF) | ((selection & 0x7) << 4)
    struct.pack_into("<H", buf, base + OFF_PUBLIC_KEY_SEL, value)
    rehash(buf, slot)


def get_public_key_sel(buf: bytes, slot: str) -> int:
    base = slot_base(slot)
    return struct.unpack_from("<H", buf, base + OFF_PUBLIC_KEY_SEL)[0]


def public_key(buf: bytes, slot: str) -> bytes:
    """The 384-byte RSA modulus this slot's manifest carries."""
    base = slot_base(slot)
    return bytes(buf[base + OFF_PUBLIC_KEY:base + OFF_PUBLIC_KEY + PUBLIC_KEY_LEN])


def verify_public_key(buf: bytes, slot: str) -> None:
    """Assert this slot's modulus is the dev0 key the ROM has in slot 0.

    :func:`verify_layout` cannot check OFF_PUBLIC_KEY -- a manifest is free to
    carry any modulus, so there is no self-consistent field to compare it with.
    The ROM supplies the missing half: ``check_pubkey_hash``
    (``manifest_crypto.c:124-136``) compares SHA-256 of the bytes at this offset
    with ``public_key_digests[0].digest``. Reproducing that comparison here proves
    two things at once, before any mutation runs:

      * OFF_PUBLIC_KEY is the modulus and not some neighbouring field, so
        :func:`corrupt_public_key` writes where it claims to; and
      * this image really does verify against ROM slot 0, so a KEY_HASH_MISMATCH
        seen afterwards is caused by the mutation rather than by an image that
        never matched.

    Only the signed images (``secure_boot.bin``, ``encrypted_boot.bin``) satisfy
    this, which is why it is a separate entry point rather than part of
    verify_layout(): the unsigned image carries no usable modulus and its slots
    are still legitimate erase / magic-corruption targets.
    """
    verify_layout(buf, slot)
    digest = hashlib.sha256(public_key(buf, slot)).digest()
    if digest != ROM_KEY0_DIGEST:
        raise AssertionError(
            f"sha256 of {slot} manifest bytes [{OFF_PUBLIC_KEY}:"
            f"{OFF_PUBLIC_KEY + PUBLIC_KEY_LEN}] is {digest.hex()}, expected the "
            f"ROM slot-0 (dev0) digest {ROM_KEY0_DIGEST.hex()}. Either "
            f"OFF_PUBLIC_KEY no longer matches the packed layout, or this image "
            f"is not signed with the key the ROM has compiled in"
        )


def corrupt_public_key(buf: bytearray, slot: str, *, byte_index: int = 0,
                       xor_mask: int = 0x01) -> None:
    """Flip a bit of the RSA modulus, so SHA-256 of it stops matching the digest.

    In-TBS, so the manifest hash is recomputed: the slot must still pass
    ``validate_manifest_header`` and ``manifest_check_integrity``
    (``manifest_load.c:477,500``) or it would be rejected as a malformed manifest
    long before the key-hash comparison it is meant to reach. Re-signing is neither
    possible nor needed -- ``check_pubkey_hash`` runs before ``rsa_3072_verify``
    (``manifest_crypto.c:195,244``), so the now-stale signature is never examined.

    One bit by default. The digest binding must fail on the smallest possible
    change, and a wholesale overwrite could not tell a hash comparison from a
    coarser sanity check on the modulus.
    """
    verify_public_key(buf, slot)
    if not 0 <= byte_index < PUBLIC_KEY_LEN:
        raise ValueError(f"modulus is {PUBLIC_KEY_LEN} bytes")
    if xor_mask == 0:
        raise ValueError("xor_mask 0 would not change anything")
    base = slot_base(slot)
    buf[base + OFF_PUBLIC_KEY + byte_index] ^= xor_mask & 0xFF
    rehash(buf, slot)
    digest = hashlib.sha256(public_key(buf, slot)).digest()
    if digest == ROM_KEY0_DIGEST:
        raise AssertionError(
            "modulus digest is unchanged after the mutation; the write did not land"
        )


def flip_signature_byte(buf: bytearray, slot: str, *, byte_index: int = 0,
                        xor_mask: int = 0x01) -> None:
    """Corrupt the signature (outside the TBS; no re-hash, no re-sign).

    Single-bit by default: an otherwise perfectly valid manifest must still fail
    RSA verification, so the smallest possible change is the strongest test.
    """
    verify_layout(buf, slot)
    base = slot_base(slot)
    if not 0 <= byte_index < 384:
        raise ValueError("signature is 384 bytes")
    idx = base + OFF_SIGNATURE + byte_index
    if xor_mask == 0:
        raise ValueError("xor_mask 0 would not change anything")
    buf[idx] ^= xor_mask & 0xFF


def set_flag_args_bit(buf: bytearray, slot: str, bit: int, value: bool) -> None:
    """Set or clear a ``boot_arguments.flag_args`` bit.

    Outside the TBS, so the manifest hash and the signature both stay valid --
    which is what makes it possible to ask "does the ROM enforce secure boot even
    though the manifest asks it not to?" of a genuinely signed image.
    """
    verify_layout(buf, slot)
    base = slot_base(slot)
    cur = struct.unpack_from("<I", buf, base + OFF_FLAG_ARGS)[0]
    new = (cur | (1 << bit)) if value else (cur & ~(1 << bit) & 0xFFFF_FFFF)
    struct.pack_into("<I", buf, base + OFF_FLAG_ARGS, new)


def get_flag_args(buf: bytes, slot: str) -> int:
    base = slot_base(slot)
    return struct.unpack_from("<I", buf, base + OFF_FLAG_ARGS)[0]


def describe(buf: bytes, slot: str) -> str:
    """One-line summary of a slot, for logging the stimulus that was applied."""
    base = slot_base(slot)
    ident = bytes(buf[base + OFF_IDENTIFIER:base + OFF_IDENTIFIER + 4])
    secver = struct.unpack_from("<H", buf, base + OFF_SECURITY_VERSION)[0]
    sigtype = buf[base + OFF_SIGNATURE_TYPE]
    pubksel = struct.unpack_from("<H", buf, base + OFF_PUBLIC_KEY_SEL)[0]
    flag_args = struct.unpack_from("<I", buf, base + OFF_FLAG_ARGS)[0]
    hash_ok = bytes(buf[base + OFF_MANIFEST_HASH:base + OFF_MANIFEST_HASH + 32]) == tbs_hash(buf, base)
    sig8 = bytes(buf[base + OFF_SIGNATURE:base + OFF_SIGNATURE + 8]).hex()
    # The modulus digest, i.e. exactly what check_pubkey_hash() compares. Logged
    # so a key-hash testcase's stimulus is readable from the run log without
    # re-deriving it: "binds_rom_key0=False" IS the planted defect.
    pubk_digest = hashlib.sha256(
        bytes(buf[base + OFF_PUBLIC_KEY:base + OFF_PUBLIC_KEY + PUBLIC_KEY_LEN])
    ).digest()
    return (
        f"{slot}@0x{base:x}: ident={ident!r} secver={secver} sigtype={sigtype} "
        f"pubksel=0x{pubksel:04x} flag_args=0x{flag_args:08x} "
        f"secure_boot_bit={(flag_args >> FLAG_ARGS_BIT_SECURE_BOOT) & 1} "
        f"tbs_hash_valid={hash_ok} sig[0:8]={sig8} "
        f"pubk_sha256[0:8]={pubk_digest[:8].hex()} "
        f"binds_rom_key0={pubk_digest == ROM_KEY0_DIGEST}"
    )
