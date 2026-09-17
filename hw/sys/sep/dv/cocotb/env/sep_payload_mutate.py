# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Payload-side mutation for a packed OCA image: the TOC, its images, re-sealing.

Companion to :mod:`sep_manifest_mutate`, which owns the manifest body. Everything here
concerns what the manifest points AT -- the payload TOC, the images it lists, and
the two digests plus one signature that seal the pair together.

WHAT SEALING MEANS HERE. Four things have to agree or the ROM rejects the slot
before any planted defect is reached:

  1. each TOC entry's ``hash`` is SHA-256 over ``payload[offset:offset+length]``;
  2. the manifest's ``payload_hash`` covers the stored bytes the consumer
     authenticates first -- the whole ciphertext when encrypted, the TOC bytes
     otherwise, which is what ``payload_hashed_length`` spans in each case;
  2b. the manifest's ``payload_hash_chain`` is the iterative chain
     ``h = SHA-256(TOC bytes)``, then ``h = SHA-256(h || SHA-256(image))`` per
     entry, which anchors the recovered plaintext back to the manifest;
  3. the manifest's ``signature_classic`` is RSA-3072 PKCS#1-v1.5-SHA256 over the
     signed region, and ``manifest_hash`` is SHA-256 of that same region.

Those last two are one commitment, not two. PKCS#1 v1.5 signs a DigestInfo
wrapping SHA-256 of the message, so the value the signature commits to IS what
``manifest_hash`` stores -- which is why a verifier can check the signature
against ``manifest_hash`` without re-reading the region, and why
:func:`reseal` must refresh ``manifest_hash`` before it signs.

:func:`verify_sealed` asserts all three, and :func:`reseal` re-establishes them in
that order -- innermost first, because each outer digest covers the one inside it.

RE-SIGNING IS POSSIBLE ON THIS TREE. The six ROM signing keys live in
``bootrom/prod/tests/signing_keys/rsa_private_key.rom_key{0..5}.pem`` and each
one's modulus hashes to the matching ``digest_rom_key<N>`` in the generated
``key_digests.c`` -- checked by :func:`verify_signing_key`. So a mutation inside
the signed region can be re-sealed and still boot, which is what a test needs when
the defect is a *value* the ROM should accept or reject on policy rather than a
broken seal.

BOTH PAYLOAD DIGESTS COME FROM THE PACKER. ``oca.payload.compute_payload_hashes``
computes them, so this module does not restate the chain construction and cannot
drift from it. A digest this layer computed itself would be a second opinion on
something the packer already owns, and a reseal that got it wrong produces an
image the ROM rejects for a field :func:`verify_sealed` called sound.

The signer is stdlib-only, by necessity rather than preference: the DV virtualenv
has no ``cryptography``. It is PKCS#1 v1.5 over SHA-256 with a 384-byte modulus,
which is the one signature type this ROM accepts (SEP-ROM-SB-090).

Run ``python3 sep_payload_mutate.py`` to check every packed image against all three
seals and the key correspondence.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

if __package__ in (None, ""):  # run directly, not imported as env.sep_payload_mutate
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env import sep_manifest_mutate as mm

K = mm.K

# ---------------------------------------------------------------------------
# Manifest-side fields that describe the payload
# ---------------------------------------------------------------------------
OFF_PAYLOAD_OFFSET = K.OFF_PAYLOAD_OFFSET
OFF_PAYLOAD_LENGTH = K.OFF_PAYLOAD_LENGTH
OFF_PAYLOAD_HASHED_LENGTH = K.OFF_PAYLOAD_HASHED_LENGTH
OFF_PAYLOAD_HASH = K.OFF_PAYLOAD_HASH
OFF_PAYLOAD_HASH_CHAIN = K.OFF_PAYLOAD_HASH_CHAIN
OFF_PAYLOAD_ENCRYPTION_CONTROL = K.OFF_PAYLOAD_ENCRYPTION_CONTROL

# ---------------------------------------------------------------------------
# Payload TOC
# ---------------------------------------------------------------------------
# Header: magic at 0, format version at 4 and 6, payload_length at 8,
# image_count at 16, 32 bytes total. An entry is 276 bytes -- type, group,
# offset, length, version, security_version, load_addr, entry_point,
# target_chiplet_id, a 64-byte hash field and a 128-byte description. Every
# offset is read from constants.py rather than restated here.
TOC_MAGIC = K.PTOC_MAGIC
TOC_OFF_PAYLOAD_LENGTH = K.OFF_TOC_PAYLOAD_LENGTH
TOC_OFF_IMAGE_COUNT = K.OFF_TOC_IMAGE_COUNT
TOC_HDR_SIZE = K.TOC_HEADER_SIZE
TOC_ENTRY_SIZE = K.TOC_ENTRY_SIZE

E_TYPE = K.OFF_TOC_ENTRY_TYPE
E_GROUP = K.OFF_TOC_ENTRY_GROUP
E_OFFSET = K.OFF_TOC_ENTRY_OFFSET
E_LENGTH = K.OFF_TOC_ENTRY_LENGTH
E_LOAD_ADDR = K.OFF_TOC_ENTRY_LOAD_ADDR
E_ENTRY_POINT = K.OFF_TOC_ENTRY_ENTRY_POINT
E_HASH = K.OFF_TOC_ENTRY_HASH

# The BL1 image's 16-byte ASCII type string, as the ROM matches it
# (rom_handoff.c SEP_BL1_IMAGE_TYPE).
IMAGE_TYPE_SEP_BL1 = b"OCAHSEP BLSTAGE1"

# ---------------------------------------------------------------------------
# Rejection codes
# ---------------------------------------------------------------------------
# Two families, and they are not interchangeable. The ROM refuses a BL1 on its
# own account with a whole OCA_BOOT_ERR_* constant; the library's rejections are
# OCA_BOOT_ERR_BASE OR-ed with a result.
MANIFEST_ERR_NO_BL1 = mm.rom_boot_err("OCA_BOOT_ERR_NO_BL1")
MANIFEST_ERR_BL1_BAD_ADDR = mm.rom_boot_err("OCA_BOOT_ERR_BL1_BAD_ADDR")
MANIFEST_ERR_BL1_TOO_LARGE = mm.rom_boot_err("OCA_BOOT_ERR_BL1_TOO_LARGE")
# The library's TOC rejection. Derived, but which result a garbage TOC lands on
# is not yet confirmed against a run -- the decryption-failure test is what will
# settle it.
MANIFEST_ERR_BAD_TOC_ID = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")

# ---------------------------------------------------------------------------
# Signing keys
# ---------------------------------------------------------------------------
RSA_KEY_BYTES = 384  # RSA-3072
SIGNING_KEY_DIR = mm._SEP_ROOT / "bootrom" / "prod" / "tests" / "signing_keys"
NUM_ROM_SIGNING_KEYS = mm.PUBK_SEL_NUM_ROM_KEYS


def rom_signing_key(index: int) -> Path:
    """PEM path for one ROM key slot.

    The Makefile's ``SEP_SIGNING_KEY`` default is slot 0's, and each slot's
    modulus hashes to the matching digest in the generated key_digests.c, so the
    index here is the same slot number ``public_key_select_classic`` names.
    """
    if not 0 <= index < NUM_ROM_SIGNING_KEYS:
        raise ValueError(f"ROM key slot {index} is outside 0..{NUM_ROM_SIGNING_KEYS - 1}")
    p = SIGNING_KEY_DIR / f"rsa_private_key.rom_key{index}.pem"
    if not p.is_file():
        raise AssertionError(f"{p} not found; re-sealing a signed slot needs it")
    return p


# ---------------------------------------------------------------------------
# Minimal DER, and PKCS#1 v1.5 signing over SHA-256
# ---------------------------------------------------------------------------
def _der_len(b: bytes, i: int) -> tuple[int, int]:
    n = b[i]
    i += 1
    if n < 0x80:
        return n, i
    k = n & 0x7F
    return int.from_bytes(b[i : i + k], "big"), i + k


def _der_tlv(b: bytes, i: int) -> tuple[int, bytes, int]:
    tag = b[i]
    ln, j = _der_len(b, i + 1)
    return tag, b[j : j + ln], j + ln


def load_rsa_private_key(pem_path: Path) -> tuple[int, int, int]:
    """Return ``(n, e, d)`` from an unencrypted RSA PEM, PKCS#1 or PKCS#8.

    The ROM signing keys are PKCS#1 (``BEGIN RSA PRIVATE KEY``): a bare
    ``RSAPrivateKey`` SEQUENCE of INTEGERs. PKCS#8 (``BEGIN PRIVATE KEY``) wraps
    the same structure in a ``PrivateKeyInfo`` with an OCTET STRING, so the label
    selects how far to unwrap before the shared parse.

    Only the three values signing needs are returned; the CRT parameters are
    ignored because ``pow(m, d, n)`` does not need them, and correctness is
    established by :func:`verify_signing_key` rather than by the parse.
    """
    text = Path(pem_path).read_text()
    pkcs1 = "BEGIN RSA PRIVATE KEY" in text
    der = base64.b64decode("".join(ln for ln in text.splitlines() if "-----" not in ln))

    tag, outer, _ = _der_tlv(der, 0)
    if tag != 0x30:
        raise AssertionError(f"{pem_path}: expected a DER SEQUENCE, got tag 0x{tag:02x}")
    if pkcs1:
        rsa_seq = outer
    else:
        i = 0
        _, _, i = _der_tlv(outer, i)  # version
        _, _, i = _der_tlv(outer, i)  # algorithm identifier
        tag, pk, _ = _der_tlv(outer, i)  # privateKey OCTET STRING
        if tag != 0x04:
            raise AssertionError(f"{pem_path}: expected an OCTET STRING, got tag 0x{tag:02x}")
        tag, rsa_seq, _ = _der_tlv(pk, 0)
        if tag != 0x30:
            raise AssertionError(f"{pem_path}: inner key is not a SEQUENCE")

    vals: list[int] = []
    j = 0
    while j < len(rsa_seq) and len(vals) < 4:
        tag, v, j = _der_tlv(rsa_seq, j)
        if tag != 0x02:
            raise AssertionError(f"{pem_path}: expected INTEGER, got tag 0x{tag:02x}")
        vals.append(int.from_bytes(v, "big"))
    _version, n, e, d = vals
    return n, e, d


# DigestInfo prefix for SHA-256, RFC 8017 A.2.4.
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _emsa_pkcs1_v15(msg: bytes, k_bytes: int) -> int:
    t = _SHA256_DIGESTINFO + hashlib.sha256(msg).digest()
    if k_bytes < len(t) + 11:
        raise ValueError("modulus too small for PKCS#1 v1.5 SHA-256")
    pad = b"\xff" * (k_bytes - len(t) - 3)
    return int.from_bytes(b"\x00\x01" + pad + b"\x00" + t, "big")


def sign_pkcs1v15_sha256(msg: bytes, n: int, d: int) -> bytes:
    """RSA-3072 PKCS#1 v1.5 signature over SHA-256(msg)."""
    k = (n.bit_length() + 7) // 8
    return pow(_emsa_pkcs1_v15(msg, k), d, n).to_bytes(k, "big")


def verify_pkcs1v15_sha256(msg: bytes, sig: bytes, n: int, e: int = 65537) -> bool:
    """True iff ``sig`` is a valid PKCS#1 v1.5 SHA-256 signature over ``msg``."""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    return pow(int.from_bytes(sig, "big"), e, n) == _emsa_pkcs1_v15(msg, k)


# ---------------------------------------------------------------------------
# Payload geometry
# ---------------------------------------------------------------------------
def _u64(buf, at: int) -> int:
    return int.from_bytes(bytes(buf[at : at + 8]), "little")


def _put_u64(buf: bytearray, at: int, value: int) -> None:
    buf[at : at + 8] = int(value).to_bytes(8, "little")


def payload_base(buf, slot: str) -> int:
    """Flash byte offset of ``slot``'s payload (manifest base + payload_offset)."""
    base = mm.slot_base(slot)
    return base + _u64(buf, base + OFF_PAYLOAD_OFFSET)


def manifest_payload_length(buf, slot: str) -> int:
    return _u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_LENGTH)


def payload_hashed_length(buf, slot: str) -> int:
    return _u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_HASHED_LENGTH)


def is_encrypted(buf, slot: str) -> bool:
    """True when ``payload_encryption_control`` asks for a decrypt."""
    base = mm.slot_base(slot) + OFF_PAYLOAD_ENCRYPTION_CONTROL
    return int.from_bytes(bytes(buf[base : base + 2]), "little") != 0


def read_bytes(buf, start: int, length: int) -> bytes:
    """Flash bytes as the ROM will see them, padding past the image with 0xFF.

    The SPI BFM's backing store and its out-of-range reads are both 0xFF, so a
    read that runs past the programmed image returns erased bytes rather than
    failing. Modelling that here is what lets a testcase declare an image size
    larger than the material actually programmed and still know, exactly, which
    bytes the ROM will hash.
    """
    have = bytes(buf[start : start + length])
    if len(have) < length:
        have += bytes([mm.ERASED_BYTE]) * (length - len(have))
    return have


def toc_entries(buf, slot: str) -> list[int]:
    """Flash offsets of each TOC entry in ``slot``."""
    p = payload_base(buf, slot)
    count = _u64(buf, p + TOC_OFF_IMAGE_COUNT)
    if not 0 < count <= 256:
        raise AssertionError(f"{slot} TOC image_count is {count}; the payload is not a TOC")
    return [p + TOC_HDR_SIZE + i * TOC_ENTRY_SIZE for i in range(count)]


def entry_type(buf, entry_off: int) -> bytes:
    """An entry's 16-byte ASCII type string."""
    return bytes(buf[entry_off + E_TYPE : entry_off + E_TYPE + 16])


def find_image(buf, slot: str, image_type: bytes = IMAGE_TYPE_SEP_BL1) -> int:
    """Flash offset of the TOC entry whose ``type`` is ``image_type``."""
    for e in toc_entries(buf, slot):
        if entry_type(buf, e) == image_type:
            return e
    present = [entry_type(buf, e) for e in toc_entries(buf, slot)]
    raise AssertionError(f"{slot} TOC has no image of type {image_type!r}; present: {present}")


def bl1_field(buf, slot: str, field_off: int) -> int:
    """Read one field of ``slot``'s BL1 TOC entry, e.g. ``bl1_field(b, s, E_LENGTH)``."""
    return _u64(buf, find_image(buf, slot) + field_off)


def describe_bl1(buf, slot: str) -> str:
    e = find_image(buf, slot)
    return (
        f"{slot} BL1: offset={_u64(buf, e + E_OFFSET)} "
        f"length={_u64(buf, e + E_LENGTH)} "
        f"load_addr=0x{_u64(buf, e + E_LOAD_ADDR):08x} "
        f"entry_point=0x{_u64(buf, e + E_ENTRY_POINT):x} "
        f"payload_length={manifest_payload_length(buf, slot)}"
    )


# ---------------------------------------------------------------------------
# The anchor, and re-sealing
# ---------------------------------------------------------------------------
def _packer_payload_hashes(buf, slot: str) -> tuple[bytes, bytes]:
    """``(payload_hash_field, payload_hash_chain_field)`` per the packer.

    Cleartext only: the chain is over plaintext, which an encrypted payload does
    not expose here.
    """
    p = payload_base(buf, slot)
    p_len = manifest_payload_length(buf, slot)
    toc_bytes = payload_hashed_length(buf, slot)
    payload = read_bytes(buf, p, p_len)
    ranges = [(_u64(buf, e + E_OFFSET), _u64(buf, e + E_LENGTH)) for e in toc_entries(buf, slot)]
    return mm.PF.compute_payload_hashes(payload, toc_bytes, ranges)


def verify_sealed(buf, slot: str, *, check_toc: bool = True) -> None:
    """Reproduce the ROM's structural and cryptographic checks over ``slot``.

    Called before every mutation and again after re-sealing. Before, it proves the
    offsets in this module address the fields they claim, so a mutation lands
    where intended. After, it proves the re-seal is complete -- an image that
    still carried a stale digest or signature would be rejected for that stale
    field, and the testcase would observe a terminal error that has nothing to do
    with the defect it planted.

    ``check_toc`` is cleared for an encrypted payload, whose TOC is ciphertext
    until the ROM decrypts it; the manifest-side checks still apply.
    """
    base = mm.slot_base(slot)
    mm.verify_layout(buf, slot)  # magic + manifest_hash over the signed region

    hashed = payload_hashed_length(buf, slot)
    p_len = manifest_payload_length(buf, slot)
    p = payload_base(buf, slot)
    if hashed > p_len:
        raise AssertionError(
            f"{slot} payload_hashed_length ({hashed}) exceeds payload_length ({p_len}); "
            f"the ROM would reject this before any check under test"
        )
    stored = bytes(buf[base + OFF_PAYLOAD_HASH : base + OFF_PAYLOAD_HASH + mm.DIGEST_LEN])
    calc = hashlib.sha256(read_bytes(buf, p, hashed)).digest()
    if stored != calc:
        raise AssertionError(
            f"{slot} payload_hash does not cover payload[:{hashed}] "
            f"(stored {stored.hex()}, computed {calc.hex()}); either the slot is not "
            f"sealed or OFF_PAYLOAD_HASH/OFF_PAYLOAD_HASHED_LENGTH are wrong"
        )

    if check_toc:
        ident = bytes(buf[p : p + 4])
        if ident != TOC_MAGIC:
            raise AssertionError(
                f"{slot} payload does not start with {TOC_MAGIC!r} (got {ident!r}); "
                f"payload_offset or the TOC layout is not what this module assumes"
            )
        toc_plen = _u64(buf, p + TOC_OFF_PAYLOAD_LENGTH)
        if toc_plen != p_len:
            raise AssertionError(
                f"{slot} TOC payload_length ({toc_plen}) != manifest payload_length "
                f"({p_len}); the ROM rejects the pair as inconsistent"
            )
        for i, e in enumerate(toc_entries(buf, slot)):
            off, ln = _u64(buf, e + E_OFFSET), _u64(buf, e + E_LENGTH)
            want = bytes(buf[e + E_HASH : e + E_HASH + mm.DIGEST_LEN])
            got = hashlib.sha256(read_bytes(buf, p + off, ln)).digest()
            if want != got:
                raise AssertionError(
                    f"{slot} image {i} ({entry_type(buf, e)!r}) digest mismatch "
                    f"(stored {want.hex()}, computed {got.hex()} over "
                    f"payload[{off}:{off + ln}]); the ROM would reject this as an "
                    f"entry-hash failure, not the planted defect"
                )

        want_hash, want_chain = _packer_payload_hashes(buf, slot)
        got_chain = bytes(
            buf[base + OFF_PAYLOAD_HASH_CHAIN : base + OFF_PAYLOAD_HASH_CHAIN + mm.DIGEST_LEN]
        )
        if got_chain != want_chain[: mm.DIGEST_LEN]:
            raise AssertionError(
                f"{slot} payload_hash_chain does not match the packer's chain over "
                f"the TOC and its images (stored {got_chain.hex()}, computed "
                f"{want_chain[: mm.DIGEST_LEN].hex()}); the ROM confirms this after "
                f"hashing every image, so a stale chain rejects the slot"
            )

    verify_signing_key(buf, slot)


def slot_signing_key(buf, slot: str) -> tuple[int, int, int]:
    """``(n, e, d)`` for the key ``slot``'s manifest selects.

    Which key signed a slot is a property of the slot, not a fixed default: the
    manifest names one of the ROM slots in ``public_key_select_classic`` and only
    that key's PEM can verify or re-sign it.
    """
    return load_rsa_private_key(rom_signing_key(mm.get_public_key_sel(buf, slot)))


def signing_key_for_slot(buf, slot: str) -> int:
    """The ROM key slot whose private key signed this slot, found from the modulus.

    Not from ``public_key_sel``. A manifest names the anchor the CONSUMER should
    check it against, which is not always a ROM slot: a fused-key manifest selects
    slot 16 or 17, where the anchor is a digest in a chiplet fuse and no private
    key exists in the tree. The modulus the slot carries is what a re-seal has to
    sign with, and it is a ROM key in every image this tree packs.

    So this matches the embedded modulus against the ROM signing keys rather than
    trusting the selector, which is correct for both: for a ROM-slot manifest the
    two agree, and for a fused-key manifest only this one has an answer.
    """
    modulus = mm.public_key_modulus(buf, slot)
    digest = hashlib.sha256(modulus).digest()
    for index in range(NUM_ROM_SIGNING_KEYS):
        if digest == mm.rom_key_digest(index):
            return index
    raise AssertionError(
        f"{slot} carries a modulus matching none of the ROM signing keys "
        f"0..{NUM_ROM_SIGNING_KEYS - 1}, so nothing in this tree can re-sign it. "
        f"sha256(modulus)={digest.hex()}"
    )


def verify_signing_key(buf, slot: str) -> int:
    """Prove the slot's signature verifies under the key that signed it. Returns the slot.

    Two things at once, and both matter for a re-seal: the signature has to verify
    under the modulus the manifest carries, and -- when the manifest names a ROM
    slot -- that modulus has to hash to the provisioned digest for it, or the ROM
    refuses the key regardless of the signature.

    The digest half is skipped for a manifest selecting a FUSED key (slot 16 or
    17). There the anchor is a digest in a chiplet fuse, which the testcase
    programs through its eFuse preload rather than the generated key_digests.c,
    so comparing against a ROM digest would assert something the ROM never checks
    on that path. The signature half still applies and is what this returns on.
    """
    sel = mm.get_public_key_sel(buf, slot)
    key_slot = signing_key_for_slot(buf, slot)
    rom_anchored = sel < NUM_ROM_SIGNING_KEYS
    if rom_anchored and sel != key_slot:
        raise AssertionError(
            f"{slot} selects ROM slot {sel} but carries rom_key{key_slot}'s modulus; "
            f"the image and the selector disagree about which key signed this manifest"
        )
    n, e, _d = load_rsa_private_key(rom_signing_key(key_slot))
    modulus = n.to_bytes(RSA_KEY_BYTES, "big")
    if modulus != mm.public_key_modulus(buf, slot):
        raise AssertionError(
            f"{slot} embedded modulus is not rom_key{key_slot}'s; the PEM and the "
            f"image disagree about which key signed this manifest"
        )
    if rom_anchored and hashlib.sha256(modulus).digest() != mm.rom_key_digest(key_slot):
        raise AssertionError(
            f"rom_key{key_slot}.pem does not hash to digest_rom_key{key_slot} in the "
            f"generated key_digests.c; the ROM would refuse this key"
        )
    base = mm.slot_base(slot)
    signed = bytes(buf[base : base + mm.SIGNED_REGION_END])
    sig = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
    if not verify_pkcs1v15_sha256(signed, sig, n, e):
        raise AssertionError(
            f"{slot} signature does not verify under rom_key{key_slot} over the "
            f"signed region; the ROM would reject the slot before the payload checks"
        )
    return key_slot


def reseal(buf: bytearray, slot: str, *, check_toc: bool = True) -> int:
    """Re-establish every seal over ``slot`` after a mutation. Returns the key slot.

    Innermost first, because each digest covers the one inside it: entry hashes,
    then payload_hash, then manifest_hash, then the signature. Doing it in any
    other order leaves an outer digest covering bytes that changed after it was
    taken.
    """
    p = payload_base(buf, slot)
    if check_toc:
        for e in toc_entries(buf, slot):
            off, ln = _u64(buf, e + E_OFFSET), _u64(buf, e + E_LENGTH)
            digest = hashlib.sha256(read_bytes(buf, p + off, ln)).digest()
            buf[e + E_HASH : e + E_HASH + mm.DIGEST_LEN] = digest

    base = mm.slot_base(slot)
    if check_toc:
        # Both fields from the packer, so the chain construction lives in one
        # place and a format change reaches this module for free.
        h_field, chain_field = _packer_payload_hashes(buf, slot)
        buf[base + OFF_PAYLOAD_HASH : base + OFF_PAYLOAD_HASH + mm.HASH_FIELD_SIZE] = h_field
        buf[base + OFF_PAYLOAD_HASH_CHAIN : base + OFF_PAYLOAD_HASH_CHAIN + mm.HASH_FIELD_SIZE] = (
            chain_field
        )
    else:
        # Ciphertext: payload_hash covers the stored bytes, and the chain covers
        # plaintext this module cannot see, so it is left alone.
        hashed = payload_hashed_length(buf, slot)
        buf[base + OFF_PAYLOAD_HASH : base + OFF_PAYLOAD_HASH + mm.DIGEST_LEN] = hashlib.sha256(
            read_bytes(buf, p, hashed)
        ).digest()

    mm.rehash(buf, slot)

    # From the modulus, not the selector: a fused-key manifest selects slot 16 or
    # 17, which names a chiplet fuse rather than a key this tree holds.
    key_slot = signing_key_for_slot(buf, slot)
    n, _e, d = load_rsa_private_key(rom_signing_key(key_slot))
    signed = bytes(buf[base : base + mm.SIGNED_REGION_END])
    sig = sign_pkcs1v15_sha256(signed, n, d)
    buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + RSA_KEY_BYTES] = sig
    return key_slot


# ---------------------------------------------------------------------------
# BL1 image mutators
# ---------------------------------------------------------------------------
def set_bl1_entry_point(buf: bytearray, slot: str, value: int | None = None) -> int:
    """Set BL1's ``entry_point``. Defaults to ``length``, the boundary value.

    ``entry_point == length`` is the smallest value SEP-ROM-MAN-060 rejects, so it
    separates a correct ``>=`` bound from a ``>`` that would accept one byte past
    the image.
    """
    verify_sealed(buf, slot)
    e = find_image(buf, slot)
    if value is None:
        value = _u64(buf, e + E_LENGTH)
    _put_u64(buf, e + E_ENTRY_POINT, value)
    reseal(buf, slot)
    return value


def set_bl1_zero_length(buf: bytearray, slot: str) -> int:
    """Set BL1's ``length`` to zero. Returns the length it had."""
    verify_sealed(buf, slot)
    e = find_image(buf, slot)
    before = _u64(buf, e + E_LENGTH)
    _put_u64(buf, e + E_LENGTH, 0)
    reseal(buf, slot)
    return before


def set_bl1_load_addr(buf: bytearray, slot: str, value: int) -> int:
    """Set BL1's ``load_addr``. Returns the address it had."""
    verify_sealed(buf, slot)
    e = find_image(buf, slot)
    before = _u64(buf, e + E_LOAD_ADDR)
    _put_u64(buf, e + E_LOAD_ADDR, value)
    reseal(buf, slot)
    return before


def corrupt_ciphertext(buf: bytearray, slot: str, *, offset: int = 0) -> int:
    """Flip a byte of an encrypted payload. Returns the flash offset touched.

    The TOC is ciphertext until the ROM decrypts it, so its entry hashes cannot be
    recomputed here -- ``check_toc`` is cleared throughout. What is re-sealed is
    the manifest's view: payload_hash covers the ciphertext, so the ROM reaches
    decryption and fails there rather than on a stale digest.
    """
    if not is_encrypted(buf, slot):
        raise AssertionError(f"{slot} payload is not encrypted; there is no ciphertext to flip")
    verify_sealed(buf, slot, check_toc=False)
    at = payload_base(buf, slot) + offset
    buf[at] ^= 0xFF
    reseal(buf, slot, check_toc=False)
    return at


def _selftest() -> int:
    """Check every packed image against all three seals."""
    build = mm._SEP_ROOT / "bootrom" / "prod" / "build"
    images = sorted(build.glob("oca_*_boot.bin"))
    if not images:
        print(f"no packed images in {build}; run `make oca-images` first")
        return 1
    print(
        f"TOC entry: type@{E_TYPE} offset@{E_OFFSET} length@{E_LENGTH} "
        f"load_addr@{E_LOAD_ADDR} entry_point@{E_ENTRY_POINT} hash@{E_HASH}"
    )
    print(f"entry size {TOC_ENTRY_SIZE}, header {TOC_HDR_SIZE}, magic {TOC_MAGIC!r}")
    print(f"signing keys: {SIGNING_KEY_DIR}\n")
    bad = sealed = skipped = 0
    for img in images:
        buf = bytearray(img.read_bytes())
        try:
            v = mm.variant_at(buf, mm.slot_base("primary"))
            if v.magic != K.OCAC_MAGIC:
                print(f"  skip {img.name} ({v.format_name})")
                skipped += 1
                continue
            if mm.signature_type(buf, "primary") == mm.SIG_TYPE_NO_SIGNATURE:
                print(f"  skip {img.name} (unsigned)")
                skipped += 1
                continue
            if not mm.can_anchor_public_key(buf, "primary"):
                print(f"  skip {img.name} (key not anchorable from the tree)")
                skipped += 1
                continue
            enc = is_encrypted(buf, "primary")
            verify_sealed(buf, "primary", check_toc=not enc)
            has_bl1 = True
            if not enc:
                try:
                    find_image(buf, "primary")
                except AssertionError:
                    has_bl1 = False  # the no-BL1 fixture, by construction
            # A reseal of an untouched image must be a no-op.
            before = bytes(buf)
            reseal(buf, "primary", check_toc=not enc)
            if bytes(buf) != before:
                print(f"  FAIL {img.name}: reseal changed an unmutated image")
                bad += 1
            # And must restore the seals after a real mutation.
            if not enc:
                mm.set_selector_bit(buf, "primary", K.SELECTOR_BIT_LIFECYCLE_PACKAGE, True)
                try:
                    verify_sealed(buf, "primary")
                except AssertionError:
                    pass
                else:
                    print(f"  FAIL {img.name}: signed-region mutation still verified")
                    bad += 1
                reseal(buf, "primary")
                verify_sealed(buf, "primary")
            sealed += 1
            if enc:
                note = "encrypted, manifest seals only"
            elif not has_bl1:
                note = "no BLSTAGE1 image, by construction"
            else:
                note = describe_bl1(buf, "primary")
            print(f"  ok   {img.name}: {note}")
        except AssertionError as exc:
            print(f"  FAIL {img.name}: {exc}")
            bad += 1
    print(f"\n{len(images)} image(s): {sealed} sealed, {skipped} skipped, {bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
