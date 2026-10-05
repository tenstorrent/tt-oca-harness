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
import hmac
from collections import namedtuple
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):  # run directly, not imported as env.sep_payload_mutate
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sep_reg_meta import sym

from env import sep_aes_golden as aes
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

OCA_TEST_CLASS_KEY = bytes(range(32))
OCA_KDF_INPUT_BYTES = 64
OCA_AES_KEY_BYTES = 32
OCA_AES_BLOCK_BYTES = 16

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

# ---------------------------------------------------------------------------
# Signing keys
# ---------------------------------------------------------------------------
RSA_KEY_BYTES = 384  # RSA-3072
SIGNING_KEY_DIR = mm._SEP_ROOT / "bootrom" / "prod" / "tests" / "signing_keys"
BUILD_DIR = mm._SEP_ROOT / "bootrom" / "prod" / "build"
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
        if is_encrypted(buf, slot):
            ok, padded = rom_view_decrypt(buf, slot, class_key=OCA_TEST_CLASS_KEY)
            if not ok:
                raise AssertionError(
                    f"{slot} ciphertext does not decrypt to valid PKCS#7 under the golden "
                    f"CLASS_KEY and the slot's own IV/KDF input; the ROM would fail the decrypt"
                )
            plain = padded[: -padded[-1]]
            _verify_plain_toc(buf, slot, plain, len(plain))
        else:
            # An entry digest may cover flash past payload_length.
            _verify_plain_toc(
                buf,
                slot,
                read_bytes(buf, p, p_len),
                p_len,
                lambda off, ln: read_bytes(buf, p + off, ln),
            )

    verify_signing_key(buf, slot)


def _verify_plain_toc(buf, slot: str, plain: bytes, plain_len: int, read_image=None) -> None:
    if read_image is None:
        read_image = lambda off, ln: bytes(plain[off : off + ln])  # noqa: E731
    base = mm.slot_base(slot)
    ident = bytes(plain[:4])
    if ident != TOC_MAGIC:
        raise AssertionError(
            f"{slot} payload does not start with {TOC_MAGIC!r} (got {ident!r}); "
            f"payload_offset or the TOC layout is not what this module assumes"
        )
    toc_plen = _u64(plain, TOC_OFF_PAYLOAD_LENGTH)
    if toc_plen != plain_len:
        if is_encrypted(buf, slot):
            raise AssertionError(
                f"{slot} TOC payload_length ({toc_plen}) != decrypted plaintext length "
                f"({plain_len}); the packer only seals a pair whose sealed geometry matches exactly"
            )
        raise AssertionError(
            f"{slot} TOC payload_length ({toc_plen}) != cleartext payload length "
            f"({plain_len}); the ROM rejects the pair as inconsistent"
        )
    ranges = _toc_ranges(plain)
    for i, (off, ln) in enumerate(ranges):
        e = toc_entry_at(i)
        want = bytes(plain[e + E_HASH : e + E_HASH + mm.DIGEST_LEN])
        got = hashlib.sha256(read_image(off, ln)).digest()
        if want != got:
            raise AssertionError(
                f"{slot} image {i} ({bytes(plain[e + E_TYPE : e + E_TYPE + 16])!r}) digest "
                f"mismatch (stored {want.hex()}, computed {got.hex()} over "
                f"payload[{off}:{off + ln}]); the ROM would reject this as an "
                f"entry-hash failure, not the planted defect"
            )

    toc_bytes = TOC_HDR_SIZE + len(ranges) * TOC_ENTRY_SIZE
    _unused_hash, want_chain = mm.PF.compute_payload_hashes(bytes(plain), toc_bytes, ranges)
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
    if not is_encrypted(buf, slot):
        raise AssertionError(f"{slot} payload is not encrypted; there is no ciphertext to flip")
    verify_sealed(buf, slot, check_toc=False)
    at = payload_base(buf, slot) + offset
    buf[at] ^= 0xFF
    # The flipped ciphertext no longer yields a valid TOC; re-seal the manifest side only.
    reseal(buf, slot, check_toc=False)
    return at


# ---------------------------------------------------------------------------
# Structural TOC mutators for the negative tests
# ---------------------------------------------------------------------------
OFF_PAYLOAD_HASHED_LEN = OFF_PAYLOAD_HASHED_LENGTH
OFF_BOOT_PAYLOAD_OFFSET = OFF_PAYLOAD_OFFSET
TOC_OFF_MAJOR_VERSION = 4
TOC_MAJOR_VERSION = 1
TOC_MAX_IMAGE_COUNT = 256
IMAGE_TYPE_SEP_BL2 = b"OCAHSEP BLSTAGE2"
SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SEP_SRAM_SIZE = 0x0004_0000


def oca_aes256_key(class_key: bytes, kdf_input: bytes) -> bytes:
    """Mirror ``oca_derive_payload_key`` for the packer's AES-256 test profile."""
    if len(class_key) != OCA_AES_KEY_BYTES or len(kdf_input) != OCA_KDF_INPUT_BYTES:
        raise ValueError("OCA AES-256 needs a 32-byte CLASS_KEY and 64-byte KDF context")
    block = bytearray(192)
    block[:13] = bytes((1, 0, 1, 0, 0, 1, 0x18, 0, 0, 0, 0, 1, 1))
    block[32:43] = b"KM_CLASS_BL"
    block[64:128] = kdf_input
    message = (1).to_bytes(2, "big") + block + (256).to_bytes(2, "big")
    return hmac.new(class_key, message, hashlib.sha256).digest()


def golden_iv(buf, slot: str) -> bytes:
    at = mm.slot_base(slot) + mm.OFF_ENCRYPTION_IV
    return bytes(buf[at : at + K.ENCRYPTION_IV_SIZE])


def manifest_kdf_input(buf, slot: str) -> bytes:
    at = mm.slot_base(slot) + mm.OFF_ENCRYPTION_KDF_INPUT
    return bytes(buf[at : at + OCA_KDF_INPUT_BYTES])


def cipher_bytes(buf, slot: str) -> bytes:
    return read_bytes(buf, payload_base(buf, slot), payload_hashed_length(buf, slot))


def encryption_type(buf, slot: str) -> int:
    return buf[mm.slot_base(slot) + K.OFF_ENCRYPTION_TYPE]


def _encrypted_payload_inputs(buf: bytes | bytearray, slot: str) -> tuple[bytes, bytes]:
    return oca_aes256_key(OCA_TEST_CLASS_KEY, manifest_kdf_input(buf, slot)), golden_iv(buf, slot)


def _pkcs7_ok(padded: bytes) -> bool:
    pad = padded[-1] if padded else 0
    return 1 <= pad <= OCA_AES_BLOCK_BYTES and padded[-pad:] == bytes([pad]) * pad


def rom_view_decrypt(
    buf,
    slot: str,
    *,
    class_key: bytes = OCA_TEST_CLASS_KEY,
    iv: bytes | None = None,
    kdf_input: bytes | None = None,
) -> tuple[bool, bytes]:
    if not is_encrypted(buf, slot):
        raise AssertionError(f"{slot} payload is not encrypted; there is nothing to decrypt")
    if encryption_type(buf, slot) != K.OcaEncryptionType.AES_256_CBC.value:
        raise AssertionError(
            f"{slot} encryption_type is 0x{encryption_type(buf, slot):02x}; only the "
            f"AES-256-CBC profile is mirrored here"
        )
    stored = read_bytes(buf, payload_base(buf, slot), manifest_payload_length(buf, slot))
    if not stored or len(stored) % OCA_AES_BLOCK_BYTES:
        raise AssertionError(f"{slot} ciphertext length {len(stored)} is not AES aligned")
    if iv is None:
        iv = golden_iv(buf, slot)
    if kdf_input is None:
        kdf_input = manifest_kdf_input(buf, slot)
    padded = aes.aes_cbc_decrypt(oca_aes256_key(class_key, kdf_input), iv, stored)
    return _pkcs7_ok(padded), bytes(padded)


def _rom_plaintext(buf, slot: str) -> bytes:
    if not is_encrypted(buf, slot):
        return read_bytes(buf, payload_base(buf, slot), manifest_payload_length(buf, slot))
    ok, padded = rom_view_decrypt(buf, slot)
    if not ok:
        raise AssertionError(f"{slot} encrypted payload has invalid PKCS#7 padding")
    return padded[: -padded[-1]]


def _payload_plaintext(buf: bytes | bytearray, slot: str) -> tuple[int, bytearray]:
    """Return the OCA plaintext payload, decrypting the packer test image when needed."""
    p = payload_base(buf, slot)
    plain = _rom_plaintext(buf, slot)
    if not is_encrypted(buf, slot):
        return p, bytearray(plain)
    if not plain.startswith(TOC_MAGIC):
        raise AssertionError(
            f"{slot} AES-256 plaintext starts {plain[:4]!r}, expected {TOC_MAGIC!r}; "
            f"the OCA test CLASS_KEY/KDF/IV contract does not match this image"
        )
    key, iv = _encrypted_payload_inputs(buf, slot)
    pad = OCA_AES_BLOCK_BYTES - (len(plain) % OCA_AES_BLOCK_BYTES)
    stored = read_bytes(buf, p, manifest_payload_length(buf, slot))
    if aes.aes_cbc_encrypt(key, iv, plain + bytes([pad]) * pad) != stored:
        raise AssertionError(f"{slot} AES-256 decrypt/encrypt round trip changed ciphertext")
    return p, bytearray(plain)


def _set_signed_encryption_field(
    buf: bytearray, slot: str, off: int, width: int, value: bytes
) -> bytes:
    if not is_encrypted(buf, slot):
        raise AssertionError(f"{slot} payload is not encrypted; its encryption fields are unused")
    if len(value) != width:
        raise ValueError(f"field at manifest offset {off} is {width} bytes, got {len(value)}")
    verify_sealed(buf, slot, check_toc=False)
    at = mm.slot_base(slot) + off
    before = bytes(buf[at : at + width])
    if value == before:
        raise ValueError(f"{slot} field at manifest offset {off} already holds {value.hex()}")
    buf[at : at + width] = value
    _refresh_outer_seals(buf, slot)
    verify_sealed(buf, slot, check_toc=False)
    return before


def set_encryption_iv(buf: bytearray, slot: str, iv: bytes) -> bytes:
    # The IV occupies the low 16 bytes of the 32-byte field.
    return _set_signed_encryption_field(
        buf, slot, mm.OFF_ENCRYPTION_IV, K.ENCRYPTION_IV_SIZE, bytes(iv)
    )


def set_encryption_kdf_input(buf: bytearray, slot: str, kdf_input: bytes) -> bytes:
    return _set_signed_encryption_field(
        buf, slot, mm.OFF_ENCRYPTION_KDF_INPUT, OCA_KDF_INPUT_BYTES, bytes(kdf_input)
    )


def _write_payload_plaintext(buf: bytearray, slot: str, plain: bytes | bytearray) -> bytes:
    """Store plaintext directly or as AES-256-CBC with the image's IV/KDF fields."""
    p = payload_base(buf, slot)
    if is_encrypted(buf, slot):
        key, iv = _encrypted_payload_inputs(buf, slot)
        pad = OCA_AES_BLOCK_BYTES - (len(plain) % OCA_AES_BLOCK_BYTES)
        stored = aes.aes_cbc_encrypt(key, iv, bytes(plain) + bytes([pad]) * pad)
    else:
        stored = bytes(plain)
    expected = manifest_payload_length(buf, slot)
    if len(stored) != expected:
        raise AssertionError(
            f"{slot} mutation changed stored payload size {expected} -> {len(stored)}"
        )
    buf[p : p + expected] = stored
    return stored


def _refresh_outer_seals(buf: bytearray, slot: str) -> int:
    """Refresh payload_hash, manifest_hash and RSA signature without parsing the TOC."""
    p = payload_base(buf, slot)
    base = mm.slot_base(slot)
    hashed = payload_hashed_length(buf, slot)
    buf[base + OFF_PAYLOAD_HASH : base + OFF_PAYLOAD_HASH + mm.DIGEST_LEN] = hashlib.sha256(
        read_bytes(buf, p, hashed)
    ).digest()
    mm.rehash(buf, slot)
    key_slot = signing_key_for_slot(buf, slot)
    n, _e, d = load_rsa_private_key(rom_signing_key(key_slot))
    signature = sign_pkcs1v15_sha256(bytes(buf[base : base + mm.SIGNED_REGION_END]), n, d)
    buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + RSA_KEY_BYTES] = signature
    return key_slot


def _toc_ranges(plain: bytes | bytearray) -> list[tuple[int, int]]:
    count = _u64(plain, TOC_OFF_IMAGE_COUNT)
    if not 0 < count <= TOC_MAX_IMAGE_COUNT:
        raise AssertionError(f"TOC image_count {count} is outside 1..{TOC_MAX_IMAGE_COUNT}")
    return [
        (
            _u64(plain, toc_entry_at(index) + E_OFFSET),
            _u64(plain, toc_entry_at(index) + E_LENGTH),
        )
        for index in range(count)
    ]


def _seal_plaintext_toc(
    buf: bytearray,
    slot: str,
    plain: bytearray,
    *,
    recompute_entry_hashes: bool = True,
    recompute_chain: bool = True,
) -> None:
    """Store a mutated plaintext TOC and refresh the requested nested OCA seals."""
    ranges = _toc_ranges(plain)
    if recompute_entry_hashes:
        for index, (offset, length) in enumerate(ranges):
            digest = hashlib.sha256(bytes(plain[offset : offset + length])).digest()
            at = toc_entry_at(index) + E_HASH
            plain[at : at + mm.DIGEST_LEN] = digest
    if recompute_chain:
        toc_bytes = TOC_HDR_SIZE + len(ranges) * TOC_ENTRY_SIZE
        _unused_hash, chain = mm.PF.compute_payload_hashes(bytes(plain), toc_bytes, ranges)
        base = mm.slot_base(slot)
        buf[base + OFF_PAYLOAD_HASH_CHAIN : base + OFF_PAYLOAD_HASH_CHAIN + mm.HASH_FIELD_SIZE] = (
            chain
        )
    _write_payload_plaintext(buf, slot, plain)
    _refresh_outer_seals(buf, slot)


def _clear_toc(buf: bytes | bytearray, slot: str) -> tuple[int, bytearray]:
    """Compatibility name returning the plaintext TOC for either storage form."""
    return _payload_plaintext(buf, slot)


def toc_plaintext(buf: bytes | bytearray, slot: str) -> bytes:
    """Return the cleartext OCA payload beginning with the PTOC header."""
    return bytes(_clear_toc(buf, slot)[1])


def set_payload_hashed_length(buf: bytearray, slot: str, value: int) -> int:
    """Set ``payload_hashed_length`` while preserving all outer seals."""
    verify_sealed(buf, slot)
    if not 0 <= value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("payload_hashed_length is 64 bits")
    base = mm.slot_base(slot) + OFF_PAYLOAD_HASHED_LENGTH
    before = _u64(buf, base)
    _put_u64(buf, base, value)
    reseal(buf, slot)
    return before


def _mutate_clear_toc(buf: bytearray, slot: str, mutate) -> None:
    """Apply ``mutate(payload)`` to plaintext, then repack and re-seal the slot."""
    verify_sealed(buf, slot)
    _p, plain = _clear_toc(buf, slot)
    mutate(plain)
    _seal_plaintext_toc(buf, slot, plain)


def set_toc_version_major(buf: bytearray, slot: str, value: int) -> int:
    before = int.from_bytes(
        toc_plaintext(buf, slot)[TOC_OFF_MAJOR_VERSION : TOC_OFF_MAJOR_VERSION + 2], "little"
    )
    _mutate_clear_toc(
        buf,
        slot,
        lambda p: p.__setitem__(
            slice(TOC_OFF_MAJOR_VERSION, TOC_OFF_MAJOR_VERSION + 2),
            (value & 0xFFFF).to_bytes(2, "little"),
        ),
    )
    return before


def set_toc_image_count(
    buf: bytearray,
    slot: str,
    value: int,
    *,
    reseal_entries: bool = True,
    hashed_to_span: bool = False,
) -> int:
    verify_sealed(buf, slot)
    if hashed_to_span:
        span = TOC_HDR_SIZE + value * TOC_ENTRY_SIZE
        if is_encrypted(buf, slot) or span > manifest_payload_length(buf, slot):
            raise AssertionError(
                f"{slot} payload_hashed_length cannot follow a {span}-byte TOC span: it "
                f"covers the whole ciphertext when encrypted and cannot exceed payload_length"
            )
        _put_u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_HASHED_LENGTH, span)
    _p, plain = _payload_plaintext(buf, slot)
    before = int.from_bytes(plain[TOC_OFF_IMAGE_COUNT : TOC_OFF_IMAGE_COUNT + 8], "little")
    encoded = (value & 0xFFFF_FFFF_FFFF_FFFF).to_bytes(8, "little")
    if reseal_entries and 0 < value <= TOC_MAX_IMAGE_COUNT:
        plain[TOC_OFF_IMAGE_COUNT : TOC_OFF_IMAGE_COUNT + 8] = encoded
        _seal_plaintext_toc(buf, slot, plain)
    else:
        # No range list exists for this count; keep stored entry hashes to reach the count check.
        plain[TOC_OFF_IMAGE_COUNT : TOC_OFF_IMAGE_COUNT + 8] = encoded
        _write_payload_plaintext(buf, slot, plain)
        _refresh_outer_seals(buf, slot)
    return before


def set_toc_payload_length(buf: bytearray, slot: str, value: int) -> int:
    before = int.from_bytes(
        toc_plaintext(buf, slot)[TOC_OFF_PAYLOAD_LENGTH : TOC_OFF_PAYLOAD_LENGTH + 8],
        "little",
    )
    _mutate_clear_toc(
        buf,
        slot,
        lambda p: p.__setitem__(
            slice(TOC_OFF_PAYLOAD_LENGTH, TOC_OFF_PAYLOAD_LENGTH + 8),
            (value & 0xFFFF_FFFF_FFFF_FFFF).to_bytes(8, "little"),
        ),
    )
    return before


def toc_entry_at(index: int) -> int:
    """Payload-relative offset of TOC entry ``index``."""
    if index < 0:
        raise ValueError("TOC entry index cannot be negative")
    return TOC_HDR_SIZE + index * TOC_ENTRY_SIZE


def set_toc_entry_length(buf: bytearray, slot: str, index: int, value: int) -> int:
    off = toc_entry_at(index) + E_LENGTH
    before = int.from_bytes(toc_plaintext(buf, slot)[off : off + 8], "little")
    _mutate_clear_toc(
        buf,
        slot,
        lambda p: p.__setitem__(
            slice(off, off + 8), (value & 0xFFFF_FFFF_FFFF_FFFF).to_bytes(8, "little")
        ),
    )
    return before


def set_toc_entry_offset(buf: bytearray, slot: str, index: int, value: int) -> int:
    off = toc_entry_at(index) + E_OFFSET
    before = int.from_bytes(toc_plaintext(buf, slot)[off : off + 8], "little")
    _mutate_clear_toc(
        buf,
        slot,
        lambda p: p.__setitem__(
            slice(off, off + 8), (value & 0xFFFF_FFFF_FFFF_FFFF).to_bytes(8, "little")
        ),
    )
    return before


def toc_entry_lower_bound(buf: bytes | bytearray, slot: str, index: int) -> int:
    """First payload offset after the TOC entry array."""
    count = _u64(toc_plaintext(buf, slot), TOC_OFF_IMAGE_COUNT)
    if not 0 <= index < count:
        raise ValueError(f"entry {index} is outside image_count {count}")
    return TOC_HDR_SIZE + count * TOC_ENTRY_SIZE


def corrupt_toc_entry_hash(
    buf: bytearray,
    slot: str,
    index: int,
    *,
    value: bytes | None = None,
    reseal: bool = True,
    byte_index: int = 0,
    xor_mask: int = 0x01,
) -> bytes:
    """Replace or byte-corrupt one entry digest, optionally refreshing outer seals."""
    if not 0 <= byte_index < mm.DIGEST_LEN or not 0 < xor_mask <= 0xFF:
        raise ValueError("invalid digest byte or XOR mask")
    if value is not None and len(value) != mm.DIGEST_LEN:
        raise ValueError(f"entry digest value must be {mm.DIGEST_LEN} bytes")
    verify_sealed(buf, slot)
    _p, plain = _payload_plaintext(buf, slot)
    at = toc_entry_at(index) + E_HASH
    if value is None:
        plain[at + byte_index] ^= xor_mask
    else:
        plain[at : at + mm.DIGEST_LEN] = value
    planted = bytes(plain[at : at + mm.DIGEST_LEN])
    if reseal:
        # Keep the deliberately bad entry digest while refreshing the chain,
        # ciphertext hash, manifest hash and signature around it.
        _seal_plaintext_toc(buf, slot, plain, recompute_entry_hashes=False)
    else:
        _write_payload_plaintext(buf, slot, plain)
    return planted


def retype_bl1_image(
    buf: bytearray,
    slot: str,
    image_type: bytes = IMAGE_TYPE_SEP_BL2,
) -> bytes:
    """Replace the BL1 entry's 16-byte OCA image type."""
    if len(image_type) != 16:
        raise ValueError("OCA TOC image types are 16 bytes")
    entry = find_image(buf, slot)
    before = entry_type(buf, entry)
    _mutate_clear_toc(
        buf,
        slot,
        lambda p: p.__setitem__(
            slice(
                entry - payload_base(buf, slot) + E_TYPE,
                entry - payload_base(buf, slot) + E_TYPE + 16,
            ),
            image_type,
        ),
    )
    return before


TocEntry = namedtuple("TocEntry", "type offset length")


def toc_entry(buf, slot: str, index: int) -> TocEntry:
    plain = _rom_plaintext(buf, slot)
    count = _u64(plain, TOC_OFF_IMAGE_COUNT)
    if not 0 <= index < count:
        raise ValueError(f"entry {index} is outside image_count {count}")
    e = toc_entry_at(index)
    return TocEntry(
        bytes(plain[e + E_TYPE : e + E_TYPE + 16]),
        _u64(plain, e + E_OFFSET),
        _u64(plain, e + E_LENGTH),
    )


def permute_toc_entries(buf: bytearray, slot: str, order: Sequence[int]) -> list[int]:
    verify_sealed(buf, slot)
    _p, plain = _payload_plaintext(buf, slot)
    count = _u64(plain, TOC_OFF_IMAGE_COUNT)
    order = list(order)
    if sorted(order) != list(range(count)):
        raise ValueError(f"order {order} is not a permutation of the {count} TOC entries")
    if order == list(range(count)):
        raise ValueError("the identity order leaves the TOC unchanged")
    entries = [
        bytes(plain[toc_entry_at(i) : toc_entry_at(i) + TOC_ENTRY_SIZE]) for i in range(count)
    ]
    for new, old in enumerate(order):
        plain[toc_entry_at(new) : toc_entry_at(new) + TOC_ENTRY_SIZE] = entries[old]
    _seal_plaintext_toc(buf, slot, plain)
    return [_u64(entries[old], E_OFFSET) for old in order]


def plaintext_diff(golden: bytes, buf: bytes, slot: str) -> list[range]:
    a, b = _rom_plaintext(golden, slot), _rom_plaintext(buf, slot)
    if len(a) != len(b):
        raise AssertionError(f"{slot} cleartext payload length changed {len(a)} -> {len(b)}")
    out: list[range] = []
    start = None
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y and start is None:
            start = i
        elif x == y and start is not None:
            out.append(range(start, i))
            start = None
    if start is not None:
        out.append(range(start, len(a)))
    return out


# TOC structural rules follow the boot manifest specification, not the validator's parser.
_U64_MAX = 0xFFFF_FFFF_FFFF_FFFF


def spec_rule_violations(buf, slot: str) -> list[str]:
    plain = _rom_plaintext(buf, slot)
    manifest_plen = manifest_payload_length(buf, slot)
    toc_plen = _u64(plain, TOC_OFF_PAYLOAD_LENGTH)
    count = _u64(plain, TOC_OFF_IMAGE_COUNT)
    major = int.from_bytes(plain[TOC_OFF_MAJOR_VERSION : TOC_OFF_MAJOR_VERSION + 2], "little")
    bad: list[str] = ["version_major"] if major > TOC_MAJOR_VERSION else []

    if count == 0:
        bad.append("count_zero")
    if TOC_HDR_SIZE + count * TOC_ENTRY_SIZE > manifest_plen:
        bad.append("span_exceeds_payload")
    hashed_rule = _hashed_length_rule(buf, slot, count, manifest_plen)
    if bad and bad != ["version_major"]:
        return bad + hashed_rule + _toc_plen_rule(buf, slot, toc_plen, manifest_plen)
    bad += hashed_rule

    extents = [
        (_u64(plain, toc_entry_at(i) + E_OFFSET), _u64(plain, toc_entry_at(i) + E_LENGTH))
        for i in range(count)
    ]
    if any(off % 8 for off, _ln in extents):
        bad.append("offset_align")
    if any(ln == 0 for _off, ln in extents):
        bad.append("length_zero")
    # Bound by the TOC's own payload_length, not the manifest's.
    if any(off + ln > _U64_MAX or off + ln > toc_plen for off, ln in extents):
        bad.append("out_of_bounds")
    if any(
        a0 < b0 + bl and b0 < a0 + al
        for i, (a0, al) in enumerate(extents)
        for b0, bl in extents[i + 1 :]
    ):
        bad.append("overlap")
    return bad + _toc_plen_rule(buf, slot, toc_plen, manifest_plen)


def _hashed_length_rule(buf, slot: str, count: int, manifest_plen: int) -> list[str]:
    hashed = payload_hashed_length(buf, slot)
    if is_encrypted(buf, slot):
        ok = TOC_HDR_SIZE + TOC_ENTRY_SIZE <= hashed == manifest_plen
    else:
        ok = hashed <= manifest_plen and hashed == TOC_HDR_SIZE + count * TOC_ENTRY_SIZE
    return [] if ok else ["hashed_length"]


def _toc_plen_rule(buf, slot: str, toc_plen: int, manifest_plen: int) -> list[str]:
    if is_encrypted(buf, slot):
        ok = (
            manifest_plen % OCA_AES_BLOCK_BYTES == 0
            and toc_plen < manifest_plen <= toc_plen + OCA_AES_BLOCK_BYTES
        )
    else:
        ok = toc_plen == manifest_plen
    return [] if ok else ["toc_plen_mismatch"]


def declare_payload_length(buf: bytearray, slot: str, payload_length: int) -> int:
    """Change the manifest payload length without moving payload bytes."""
    verify_sealed(buf, slot)
    base = mm.slot_base(slot) + OFF_PAYLOAD_LENGTH
    before = _u64(buf, base)
    _put_u64(buf, base, payload_length)
    mm.rehash(buf, slot)
    key_slot = signing_key_for_slot(buf, slot)
    n, _e, d = load_rsa_private_key(rom_signing_key(key_slot))
    mbase = mm.slot_base(slot)
    sig = sign_pkcs1v15_sha256(bytes(buf[mbase : mbase + mm.SIGNED_REGION_END]), n, d)
    buf[mbase + mm.OFF_SIGNATURE : mbase + mm.OFF_SIGNATURE + RSA_KEY_BYTES] = sig
    return before


def set_overlapping_payload_offset(buf: bytearray, slot: str, value: int) -> int:
    """Move payload_offset into the manifest body."""
    base = mm.slot_base(slot) + OFF_PAYLOAD_OFFSET
    before = _u64(buf, base)
    _put_u64(buf, base, value)
    mm.rehash(buf, slot)
    key_slot = signing_key_for_slot(buf, slot)
    n, _e, d = load_rsa_private_key(rom_signing_key(key_slot))
    mbase = mm.slot_base(slot)
    sig = sign_pkcs1v15_sha256(bytes(buf[mbase : mbase + mm.SIGNED_REGION_END]), n, d)
    buf[mbase + mm.OFF_SIGNATURE : mbase + mm.OFF_SIGNATURE + RSA_KEY_BYTES] = sig
    return before


def bl1_sram_source(buf: bytes | bytearray, slot: str) -> int:
    """SRAM source address from the OCA payload and BL1 entry offsets."""
    relative = payload_base(buf, slot) - mm.slot_base(slot)
    return SEP_SRAM_BASE + relative + bl1_field(buf, slot, E_OFFSET)


def repack_payload(
    buf: bytearray,
    slot: str,
    payload_length: int,
    *,
    bl1_offset: int | None = None,
) -> dict[str, int]:
    """Rebuild a one-image cleartext OCA payload at an exact length."""
    verify_sealed(buf, slot)
    if is_encrypted(buf, slot):
        raise AssertionError("repack_payload requires a cleartext OCA payload")
    entries = toc_entries(buf, slot)
    if len(entries) != 1 or entry_type(buf, entries[0]) != IMAGE_TYPE_SEP_BL1:
        raise AssertionError("repack_payload requires one SEP BL1 TOC entry")
    p = payload_base(buf, slot)
    old_payload_length = manifest_payload_length(buf, slot)
    entry = entries[0]
    old_offset = _u64(buf, entry + E_OFFSET)
    bl1_length = _u64(buf, entry + E_LENGTH)
    body = read_bytes(buf, p + old_offset, bl1_length)
    region = TOC_HDR_SIZE + TOC_ENTRY_SIZE
    if bl1_offset is None:
        bl1_offset = old_offset if old_offset + bl1_length <= payload_length else (region + 7) & ~7
    if bl1_offset < region or bl1_offset % 8 or bl1_offset + bl1_length > payload_length:
        raise ValueError(
            f"BL1 at offset {bl1_offset} length {bl1_length} does not fit an "
            f"aligned {payload_length}-byte OCA payload"
        )

    payload = bytearray(payload_length)
    payload[:TOC_HDR_SIZE] = read_bytes(buf, p, TOC_HDR_SIZE)
    payload[TOC_HDR_SIZE:region] = read_bytes(buf, entry, TOC_ENTRY_SIZE)
    _put_u64(payload, TOC_OFF_PAYLOAD_LENGTH, payload_length)
    _put_u64(payload, TOC_HDR_SIZE + E_OFFSET, bl1_offset)
    payload[bl1_offset : bl1_offset + bl1_length] = body
    payload[TOC_HDR_SIZE + E_HASH : TOC_HDR_SIZE + E_HASH + mm.DIGEST_LEN] = hashlib.sha256(
        body
    ).digest()
    buf[p : p + payload_length] = payload
    base = mm.slot_base(slot)
    _put_u64(buf, base + OFF_PAYLOAD_LENGTH, payload_length)
    _put_u64(buf, base + OFF_PAYLOAD_HASHED_LENGTH, region)
    reseal(buf, slot)
    return {
        "payload_flash_offset": p,
        "payload_length_before": old_payload_length,
        "payload_length": payload_length,
        "toc_region": region,
        "bl1_offset": bl1_offset,
        "bl1_length": bl1_length,
    }


def _selftest_stimulus() -> None:
    # Independent KAT for the C implementation's AES-256 KBKDF profile.
    kat_kdf = bytes.fromhex("a5" * 16 + "b6" * 16 + "c7" * 16 + "d8" * 16)
    kat_key = bytes.fromhex("da4e1f270faaf863b1ebb284b30e2cc935a10d9e25c5c7e6adc25158b9137292")
    assert oca_aes256_key(OCA_TEST_CLASS_KEY, kat_kdf) == kat_key, (
        "KBKDF does not reproduce the AES-256 KAT; the ROM's payload key cannot be predicted"
    )

    golden = bytes(Path(BUILD_DIR / "oca_encrypted_boot.bin").read_bytes())
    buf = bytearray(golden)
    verify_sealed(buf, "primary")
    old_iv = set_encryption_iv(buf, "primary", bytes(b ^ 0xAA for b in golden_iv(buf, "primary")))
    assert rom_view_decrypt(buf, "primary")[0] is True
    assert rom_view_decrypt(buf, "primary", iv=old_iv)[1][:4] == b"PTOC"
    assert cipher_bytes(buf, "primary") == cipher_bytes(golden, "primary")
    assert plaintext_diff(golden, buf, "primary") == [range(0, OCA_AES_BLOCK_BYTES)]
    buf = bytearray(golden)
    set_encryption_kdf_input(buf, "primary", bytes.fromhex("deadbeefcafebabe0123456789abcdef" * 4))
    assert rom_view_decrypt(buf, "primary")[0] is False
    assert cipher_bytes(buf, "primary") == cipher_bytes(golden, "primary")

    enc_buf = bytearray(Path(BUILD_DIR / "oca_encrypted_boot.bin").read_bytes())
    enc_toc_plen = _u64(_rom_plaintext(enc_buf, "primary"), TOC_OFF_PAYLOAD_LENGTH)
    set_toc_payload_length(enc_buf, "primary", enc_toc_plen - 8)
    assert spec_rule_violations(enc_buf, "primary") == ["out_of_bounds", "toc_plen_mismatch"]

    multi_golden = Path(BUILD_DIR / "oca_multi_image_boot.bin").read_bytes()
    clear_toc_plen = _u64(
        _rom_plaintext(bytearray(multi_golden), "primary"), TOC_OFF_PAYLOAD_LENGTH
    )
    clear_buf = bytearray(multi_golden)
    set_toc_payload_length(clear_buf, "primary", clear_toc_plen - 8)
    assert spec_rule_violations(clear_buf, "primary") == ["out_of_bounds", "toc_plen_mismatch"]

    multi = bytearray(multi_golden)
    assert spec_rule_violations(multi, "primary") == []
    permute_toc_entries(multi, "primary", [2, 1, 0])
    verify_sealed(multi, "primary")
    assert spec_rule_violations(multi, "primary") == []
    permuted = bytes(multi)
    set_toc_entry_offset(multi, "primary", 1, toc_entry(multi, "primary", 2).offset + 8)
    verify_sealed(multi, "primary")
    assert spec_rule_violations(multi, "primary") == ["overlap"]
    e1 = toc_entry_at(1)
    allowed = set(range(e1 + E_OFFSET, e1 + E_OFFSET + 8)) | set(
        range(e1 + E_HASH, e1 + E_HASH + mm.DIGEST_LEN)
    )
    changed = {i for r in plaintext_diff(permuted, multi, "primary") for i in r}
    assert changed and changed <= allowed, f"overlap stimulus touched {sorted(changed - allowed)}"
    multi = bytearray(permuted)
    set_toc_entry_offset(multi, "primary", 1, toc_entry(multi, "primary", 0).offset + 8)
    assert spec_rule_violations(multi, "primary") == ["out_of_bounds", "overlap"]

    cap_golden = Path(BUILD_DIR / "oca_toc_cap_boot.bin").read_bytes()
    cap = bytearray(cap_golden)
    assert spec_rule_violations(cap, "primary") == []
    set_toc_image_count(cap, "primary", 2, reseal_entries=False)
    assert spec_rule_violations(cap, "primary") == ["hashed_length", "length_zero"]
    cap = bytearray(cap_golden)
    set_toc_image_count(cap, "primary", 2, reseal_entries=False, hashed_to_span=True)
    assert payload_hashed_length(cap, "primary") == TOC_HDR_SIZE + 2 * TOC_ENTRY_SIZE
    assert spec_rule_violations(cap, "primary") == ["length_zero"]
    short = bytearray(Path(BUILD_DIR / "oca_encrypted_boot.bin").read_bytes())
    at = mm.slot_base("primary") + OFF_PAYLOAD_HASHED_LENGTH
    _put_u64(short, at, manifest_payload_length(short, "primary") - OCA_AES_BLOCK_BYTES)
    assert spec_rule_violations(short, "primary") == ["hashed_length"]
    for name in ("oca_secure_boot.bin", "oca_encrypted_boot.bin"):
        vbuf = bytearray(Path(BUILD_DIR / name).read_bytes())
        set_toc_version_major(vbuf, "primary", TOC_MAJOR_VERSION)
        assert spec_rule_violations(vbuf, "primary") == [], name
        set_toc_version_major(vbuf, "primary", TOC_MAJOR_VERSION + 1)
        assert spec_rule_violations(vbuf, "primary") == ["version_major"], name
    print("stimulus helpers: KAT, IV, KDF, permute, overlap, hashed_length, version_major ok")


def _selftest() -> int:
    """Check every packed image against all three seals."""
    _selftest_stimulus()
    build = BUILD_DIR
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
            aes256 = (
                enc and encryption_type(buf, "primary") == K.OcaEncryptionType.AES_256_CBC.value
            )
            verify_sealed(buf, "primary", check_toc=aes256 or not enc)
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
            if aes256:
                note = "encrypted, TOC and chain checked on the decrypted plaintext"
            elif enc:
                note = "encrypted, not AES-256-CBC: manifest seals only"
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
