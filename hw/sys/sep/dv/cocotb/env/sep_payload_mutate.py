# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Payload/TOC mutation for boot testcases whose defect lives PAST the crypto chain.

WHY THIS IS A SEPARATE MODULE FROM ``sep_manifest_mutate``. That module states its
own operating rule in its docstring: every mutation it performs is rejected before
the RSA step, so the stale signature is never reached and re-signing is
"deliberately not done". The defects here are the opposite case. BL1 size, BL1
entry point and post-decrypt TOC content are all validated by
``validate_manifest_payload()`` / ``check_bl1_image()``, which run in
``manifest_load.c`` AFTER ``manifest_crypto_validate()`` has verified the
signature. A payload mutation that is not
re-sealed therefore never reaches the check it is aimed at: it dies at
``PLD_HASH_MISMATCH`` (``manifest_crypto.c``), or at ``SIG_FAILED`` once
``payload_hash`` -- which sits INSIDE the TBS at offset 552 -- is corrected.

So these mutations must re-seal the slot, in this order:

    per-image hash  ->  payload_hash  ->  manifest_hash  ->  RSA signature

RE-SIGNING IS POSSIBLE HERE, and that is not a shortcut. The images under test are
signed with the dev0 test key, whose private half ships in the tree at
``bootrom/prod/tools/tt-boot-manifest/tests/signing_keys/rsa_private_key.dev0.pem``
and whose modulus digest is the ROM's own key slot 0
(``bootrom/prod/src/key_digests.c``). Re-signing keeps the ROM's signature
check ENABLED and passing on a legitimately signed image; it does not bypass,
weaken or stub anything. The alternative -- running these testcases with secure
boot off -- would be the weaker test, because the ROM would then skip the whole
crypto chain and the BL1 verdict would be reached by a different path than the one
production uses.

SIGNING USES ONLY THE STANDARD LIBRARY. The DV virtualenv has no ``cryptography``
module, so :func:`sign_pkcs1v15_sha256` implements EMSA-PKCS1-v1_5 directly (the
packer's scheme: ``manifest_signing.py``, ``PKCS1v15()`` + ``SHA256``).
:func:`verify_signing_key` is what makes that trustworthy: it re-derives the
signature of the UNMUTATED slot and requires it to equal the shipped bytes
exactly. A wrong padding, a wrong digest prefix or a wrong TBS boundary cannot
survive that, so the re-sealed image is signed by construction rather than by
assertion.

ANCHORING, generally. Every entry point calls :func:`verify_sealed` on the image
BEFORE mutating it. That reproduces the ROM's own checks -- TOC magic, the
TOC/manifest payload-length agreement, ``payload_hash`` over
``payload_hashed_length``, each image's digest, ``manifest_hash`` over the TBS,
and an RSA verification against the manifest's own modulus -- so a packer change
that moved any field turns into a loud failure here instead of a negative test
that passes for the wrong reason.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from env import sep_manifest_mutate as mm

# ── Manifest fields this module touches (manifest.h) ──────────────────
# All are inside the TBS except boot_arguments, so writing any of them obliges a
# rehash + re-sign. verify_sealed() cross-checks every one against real bytes.
OFF_PAYLOAD_HASH = 552          # 32 B, SHA-256 over payload[:payload_hashed_length]
OFF_PAYLOAD_HASHED_LEN = 584    # uint64
OFF_PAYLOAD_LENGTH = 600        # uint64
OFF_BOOT_PAYLOAD_OFFSET = 1160  # int64, first field of boot_arguments
OFF_USAGE_FLAGS = 92            # uint32, usage_constraints.flags (16 + 76)

# ── TOC layout (manifest.h) ──────────────────────────────────────────
TOC_MAGIC = b"PTOC"             # TOC_HEADER_MAGIC_WORD 0x434f5450
TOC_HDR_SIZE = 32
TOC_ENTRY_SIZE = 216
TOC_OFF_PAYLOAD_LENGTH = 8      # uint64 in the header
TOC_OFF_IMAGE_COUNT = 16        # uint64 in the header

# Field offsets within a toc_entry.
E_TYPE = 0
E_OFFSET = 8
E_LENGTH = 16
E_LOAD_ADDR = 32
E_ENTRY_POINT = 40
E_HASH = 56

# Image types, manifest.h -- a 6-byte ASCII tag packed little-endian into a u64.
# is_known_image_type() (manifest_load.c) accepts exactly these four and rejects
# everything else with MANIFEST_ERR_BAD_IMAGE_TYPE, so a TOC that must stay
# structurally valid while carrying no SEP_BL1 has to relabel to one of the other
# three rather than to an arbitrary value.
IMAGE_TYPE_SEP_BL1 = 0x0000_314C_4250_4553
IMAGE_TYPE_SEP_BL2 = 0x0000_324C_4250_4553
IMAGE_TYPE_SMC_BL1 = 0x0000_314C_4243_4D53
IMAGE_TYPE_SMC_BL2 = 0x0000_324C_4243_4D53
KNOWN_IMAGE_TYPES = (IMAGE_TYPE_SEP_BL1, IMAGE_TYPE_SEP_BL2,
                     IMAGE_TYPE_SMC_BL1, IMAGE_TYPE_SMC_BL2)

# manifest.h -- sizeof(struct toc_header) and sizeof(struct toc_entry).
def toc_region_bytes(image_count: int) -> int:
    """Bytes the TOC header and ``image_count`` entries occupy.

    The ROM computes the same number and uses it twice: as the lower bound every
    image body must start at, and as the region it requires the payload to be big
    enough to hold (``manifest_load.c``, ``TOC_REGION_OOB=``).
    """
    return TOC_HDR_SIZE + image_count * TOC_ENTRY_SIZE


# Where the ROM stages the manifest, manifest_load.c: the DMA destination is
# SRAM_BASE, and manifest_payload_address() resolves relative to it. NOT
# check_bl1_image()'s window -- that one is ICCM (SEP_IRAM_BASE / SEP_IRAM_SIZE,
# manifest.h), and confusing the two would send a reader to the wrong ROM check.
SEP_SRAM_BASE = 0x1000_0000
SEP_SRAM_SIZE = 0x0004_0000

# manifest.h -- both check_bl1_image() arms return this one error code.
MANIFEST_ERR_BL1_BAD_ADDR = 0x0003_000A
# manifest.h
MANIFEST_ERR_BAD_TOC_ID = 0x0003_0005

# The dev0 signing key, relative to the repo's sep root.
_SEP_ROOT = Path(__file__).resolve().parents[3]
DEV0_KEY = (_SEP_ROOT / "bootrom" / "prod" / "tools" / "tt-boot-manifest"
            / "tests" / "signing_keys" / "rsa_private_key.dev0.pem")

# EMSA-PKCS1-v1_5 DigestInfo prefix for SHA-256 (RFC 8017 section 9.2, note 1).
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")

RSA_KEY_BYTES = 384  # RSA-3072


# ── minimal DER / PKCS#8 reader ───────────────────────────────────────────────
def _der_len(b: bytes, i: int) -> tuple[int, int]:
    n = b[i]
    i += 1
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(b[i:i + k], "big")
        i += k
    return n, i


def _der_tlv(b: bytes, i: int) -> tuple[int, bytes, int]:
    tag = b[i]
    i += 1
    ln, i = _der_len(b, i)
    return tag, b[i:i + ln], i + ln


def load_rsa_private_key(pem_path: Path = DEV0_KEY) -> tuple[int, int, int]:
    """Return ``(n, e, d)`` from an unencrypted PKCS#8 RSA PEM.

    Only the three values signing needs are returned; the CRT parameters are
    ignored because ``pow(m, d, n)`` does not need them and correctness is
    established by :func:`verify_signing_key` rather than by the parse.
    """
    text = Path(pem_path).read_text()
    body = "".join(line for line in text.splitlines() if "-----" not in line)
    der = base64.b64decode(body)
    tag, info, _ = _der_tlv(der, 0)  # PrivateKeyInfo
    if tag != 0x30:
        raise AssertionError(f"{pem_path}: expected a DER SEQUENCE, got tag 0x{tag:02x}")
    i = 0
    _, _, i = _der_tlv(info, i)       # version
    _, _, i = _der_tlv(info, i)       # algorithm identifier
    tag, pk, _ = _der_tlv(info, i)    # privateKey OCTET STRING
    if tag != 0x04:
        raise AssertionError(f"{pem_path}: expected an OCTET STRING, got tag 0x{tag:02x}")
    tag, rsa_seq, _ = _der_tlv(pk, 0)  # RSAPrivateKey
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


def _emsa_pkcs1_v15(msg: bytes, k_bytes: int) -> int:
    t = _SHA256_DIGESTINFO + hashlib.sha256(msg).digest()
    if k_bytes < len(t) + 11:
        raise AssertionError("modulus too small for a SHA-256 PKCS#1 v1.5 signature")
    em = b"\x00\x01" + b"\xff" * (k_bytes - len(t) - 3) + b"\x00" + t
    return int.from_bytes(em, "big")


def sign_pkcs1v15_sha256(msg: bytes, n: int, d: int) -> bytes:
    """RSASSA-PKCS1-v1_5 sign, matching ``manifest_signing.py``."""
    k = (n.bit_length() + 7) // 8
    return pow(_emsa_pkcs1_v15(msg, k), d, n).to_bytes(k, "big")


def verify_pkcs1v15_sha256(msg: bytes, sig: bytes, n: int, e: int = 65537) -> bool:
    """Public-key verification, so an image can be checked without the private key."""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    return pow(int.from_bytes(sig, "big"), e, n) == _emsa_pkcs1_v15(msg, k)


# ── slot geometry ────────────────────────────────────────────────────────────
def _u64(buf, at: int) -> int:
    return int.from_bytes(bytes(buf[at:at + 8]), "little")


def _put_u64(buf: bytearray, at: int, value: int) -> None:
    buf[at:at + 8] = int(value).to_bytes(8, "little")


def payload_base(buf, slot: str) -> int:
    """Flash byte offset of ``slot``'s payload (manifest base + payload_offset)."""
    base = mm.slot_base(slot)
    off = int.from_bytes(bytes(buf[base + OFF_BOOT_PAYLOAD_OFFSET:
                                   base + OFF_BOOT_PAYLOAD_OFFSET + 8]),
                         "little", signed=True)
    return base + off


def manifest_payload_length(buf, slot: str) -> int:
    return _u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_LENGTH)


def payload_hashed_length(buf, slot: str) -> int:
    return _u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_HASHED_LEN)


def is_encrypted(buf, slot: str) -> bool:
    """usage_constraints.flags bit 1, manifest.h."""
    base = mm.slot_base(slot)
    flags = int.from_bytes(bytes(buf[base + OFF_USAGE_FLAGS:base + OFF_USAGE_FLAGS + 4]),
                           "little")
    return bool((flags >> 1) & 1)


def read_bytes(buf, start: int, length: int) -> bytes:
    """Flash bytes as the ROM will see them, padding past the image with 0xFF.

    The SPI BFM's backing store and its out-of-range reads are both 0xFF
    (``ocah_spi_flash.py``), so a read that runs past the programmed
    image returns erased bytes rather than failing. Modelling that here is what
    lets a testcase declare an image size larger than the material actually
    programmed and still know, exactly, which bytes the ROM will hash.
    """
    have = bytes(buf[start:start + length])
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


def find_image(buf, slot: str, image_type: int = IMAGE_TYPE_SEP_BL1) -> int:
    """Flash offset of the TOC entry whose ``type`` is ``image_type``."""
    for e in toc_entries(buf, slot):
        if _u64(buf, e + E_TYPE) == image_type:
            return e
    raise AssertionError(
        f"{slot} TOC has no image of type 0x{image_type:x}; "
        f"types present: {[hex(_u64(buf, e + E_TYPE)) for e in toc_entries(buf, slot)]}"
    )


def bl1_field(buf, slot: str, field_off: int) -> int:
    """Read one field of ``slot``'s BL1 TOC entry, e.g. ``bl1_field(b, s, E_LENGTH)``."""
    return _u64(buf, find_image(buf, slot) + field_off)


def describe_bl1(buf, slot: str) -> str:
    e = find_image(buf, slot)
    return (f"{slot} BL1: offset={_u64(buf, e + E_OFFSET)} "
            f"length={_u64(buf, e + E_LENGTH)} "
            f"load_addr=0x{_u64(buf, e + E_LOAD_ADDR):08x} "
            f"entry_point=0x{_u64(buf, e + E_ENTRY_POINT):x} "
            f"payload_length={manifest_payload_length(buf, slot)}")


# ── the anchor ───────────────────────────────────────────────────────────────
def verify_sealed(buf, slot: str, *, check_toc: bool = True) -> None:
    """Reproduce the ROM's structural and cryptographic checks over ``slot``.

    Called before every mutation and again after re-sealing. Before, it proves the
    offsets in this module address the fields they claim, so a mutation lands where
    intended. After, it proves the re-seal is complete -- an image that still
    carries a stale hash or signature would be rejected by the ROM for that stale
    field, and the testcase would then observe a terminal error that has nothing to
    do with the defect it planted.

    ``check_toc`` is cleared for an encrypted payload, whose TOC is ciphertext
    until the ROM decrypts it; the manifest-side checks still apply.
    """
    base = mm.slot_base(slot)
    mm.verify_layout(buf, slot)  # magic + manifest_hash == sha256(TBS)

    hashed = payload_hashed_length(buf, slot)
    p_len = manifest_payload_length(buf, slot)
    p = payload_base(buf, slot)
    if hashed > p_len:
        raise AssertionError(
            f"{slot} payload_hashed_length ({hashed}) exceeds payload_length ({p_len}); "
            f"validate_manifest_header would reject this before any check under test"
        )
    stored = bytes(buf[base + OFF_PAYLOAD_HASH:base + OFF_PAYLOAD_HASH + 32])
    calc = hashlib.sha256(read_bytes(buf, p, hashed)).digest()
    if stored != calc:
        raise AssertionError(
            f"{slot} payload_hash does not equal sha256(payload[:{hashed}]) "
            f"(stored {stored.hex()}, computed {calc.hex()}); either the slot is not "
            f"sealed or OFF_PAYLOAD_HASH/OFF_PAYLOAD_HASHED_LEN are wrong"
        )

    if check_toc:
        ident = bytes(buf[p:p + 4])
        if ident != TOC_MAGIC:
            raise AssertionError(
                f"{slot} payload does not start with {TOC_MAGIC!r} (got {ident!r}); "
                f"payload_offset or the TOC layout is not what this module assumes"
            )
        toc_plen = _u64(buf, p + TOC_OFF_PAYLOAD_LENGTH)
        if toc_plen != p_len:
            raise AssertionError(
                f"{slot} TOC payload_length ({toc_plen}) != manifest payload_length "
                f"({p_len}); validate_manifest_payload rejects this as TOC_PLEN_MISMATCH"
            )
        for i, e in enumerate(toc_entries(buf, slot)):
            off, ln = _u64(buf, e + E_OFFSET), _u64(buf, e + E_LENGTH)
            want = bytes(buf[e + E_HASH:e + E_HASH + 32])
            got = hashlib.sha256(read_bytes(buf, p + off, ln)).digest()
            if want != got:
                raise AssertionError(
                    f"{slot} image {i} digest mismatch (stored {want.hex()}, "
                    f"computed {got.hex()} over payload[{off}:{off + ln}]); the ROM "
                    f"would reject this as IMAGE_HASH_MISMATCH, not the planted defect"
                )

    n, e_pub, _d = load_rsa_private_key()
    tbs = bytes(buf[base:base + mm.TBS_LEN])
    sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
    if not verify_pkcs1v15_sha256(tbs, sig, n):
        raise AssertionError(
            f"{slot} signature does not verify against the dev0 modulus; the ROM "
            f"would reject this slot as SIG_FAILED before reaching the payload checks"
        )


def verify_signing_key(buf, slot: str) -> None:
    """Prove the local signer reproduces the packer's signature, byte for byte.

    This is the check every re-sealed image depends on. If
    :func:`sign_pkcs1v15_sha256` regenerates the SHIPPED signature of an untouched
    slot exactly, then the padding, the digest prefix, the TBS boundary and the key
    parse are all correct, and a signature it produces over modified bytes is a
    genuine dev0 signature. Without this the re-seal would be an unverified claim,
    and its failure mode -- the ROM rejecting the slot as SIG_FAILED -- looks like a
    plausible negative-test result.
    """
    base = mm.slot_base(slot)
    n, _e, d = load_rsa_private_key()
    tbs = bytes(buf[base:base + mm.TBS_LEN])
    shipped = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
    mine = sign_pkcs1v15_sha256(tbs, n, d)
    if mine != shipped:
        raise AssertionError(
            f"local re-signing does not reproduce the shipped {slot} signature "
            f"(computed {mine[:8].hex()}..., shipped {shipped[:8].hex()}...); the "
            f"signing scheme here no longer matches the packer, so a re-sealed image "
            f"would be rejected as SIG_FAILED and the testcase would prove nothing"
        )


# ── re-sealing ───────────────────────────────────────────────────────────────
def rehash_image(buf: bytearray, slot: str, entry: int) -> None:
    """Recompute one TOC entry's digest over its (possibly resized) body."""
    p = payload_base(buf, slot)
    off, ln = _u64(buf, entry + E_OFFSET), _u64(buf, entry + E_LENGTH)
    buf[entry + E_HASH:entry + E_HASH + 32] = hashlib.sha256(
        read_bytes(buf, p + off, ln)).digest()


def reseal(buf: bytearray, slot: str) -> None:
    """payload_hash -> manifest_hash -> signature, in the only order that works.

    Each step consumes the previous one's output: ``payload_hash`` lives in the TBS,
    ``manifest_hash`` is the digest of the TBS, and the signature is over the TBS.
    Per-image digests are NOT recomputed here -- a testcase that resizes an image
    must call :func:`rehash_image` itself, so that leaving an image digest stale is
    a deliberate choice rather than a silent side effect of re-sealing.
    """
    base = mm.slot_base(slot)
    p = payload_base(buf, slot)
    hashed = payload_hashed_length(buf, slot)
    buf[base + OFF_PAYLOAD_HASH:base + OFF_PAYLOAD_HASH + 32] = hashlib.sha256(
        read_bytes(buf, p, hashed)).digest()
    mm.rehash(buf, slot)  # manifest_hash = sha256(TBS)
    n, _e, d = load_rsa_private_key()
    tbs = bytes(buf[base:base + mm.TBS_LEN])
    buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + RSA_KEY_BYTES] = \
        sign_pkcs1v15_sha256(tbs, n, d)


# ── the mutations ────────────────────────────────────────────────────────────
def set_bl1_entry_point(buf: bytearray, slot: str, value: int | None = None) -> int:
    """Make BL1's ``entry_point`` violate ``entry_point < length``.

    ``check_bl1_image`` returns 2 for this (``manifest.h``), which
    ``validate_manifest_payload`` prints as ``BL1_ENTRY_RANGE`` before returning
    ``MANIFEST_ERR_BL1_BAD_ADDR`` (``manifest_load.c``).

    The default is ``entry_point == length`` exactly: the smallest value the
    condition rejects. A larger value would pass just as well against a ROM that
    had mistakenly written ``>`` instead of ``>=``, so the boundary is the only
    choice that pins the comparison.

    The image BODY is untouched, so its digest stays valid and the run reaches the
    BL1 check rather than dying at IMAGE_HASH_MISMATCH. Returns the value written.
    """
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)
    entry = find_image(buf, slot)
    length = _u64(buf, entry + E_LENGTH)
    if value is None:
        value = length
    if value < length:
        raise ValueError(
            f"entry_point 0x{value:x} is below length 0x{length:x}; that is a VALID "
            f"entry point and would not exercise the check under test"
        )
    _put_u64(buf, entry + E_ENTRY_POINT, value)
    reseal(buf, slot)
    verify_sealed(buf, slot)
    return value


def set_bl1_zero_length(buf: bytearray, slot: str) -> int:
    """Give BL1 a zero image size.

    WHICH SIZE CLASS THIS ROM CAN ACTUALLY BE SHOWN. Three exist (zero, larger
    than IRAM, larger than the maximum BL1 size), and only the first is
    reachable at a sane simulation cost. The reason is check ordering
    inside ``validate_manifest_payload``:

      * ``manifest_load.c`` rejects ``offset + length > payload_length`` as
        ``MANIFEST_ERR_IMAGE_OOB`` before anything BL1-specific runs, so an
        oversized length can only be reached by GROWING the payload to match.
      * ``check_bl1_image``'s containment arm (``manifest.h``,
        ``BL1_ADDR_RANGE``) only fires once ``load_addr + length`` leaves the
        256 KiB ICCM window. With the shipped ``load_addr`` of 0xC0000000 that
        needs length > 0x40000, i.e. a >256 KiB payload -- roughly 160 ms of extra
        simulated SPI time per slot at this TB's ~610 ns/byte, on both slots.
      * The explicit ``length == 0 || length > SEP_IRAM_SIZE`` gate at
        ``rom_handoff.c`` (``BL1_SIZE`` / ``MANIFEST_ERR_BL1_TOO_LARGE``)
        is downstream of manifest validation, and ``manifest_load.c``
        says so in as many words: by the time handoff runs the slot has already
        been accepted. Both of its arms are therefore already rejected upstream.

    So zero is the class this ROM demonstrates cheaply and unambiguously, at
    ``manifest_load.c``: ``IMAGE_LEN_ZERO idx=<i>`` then
    ``MANIFEST_ERR_IMAGE_OOB``. The index in the marker is what makes the verdict
    attributable -- this payload's TOC holds exactly one image and it is the BL1,
    so ``idx=0`` names the entry that was mutated.

    The body digest is recomputed over the now-empty range even though the ROM
    rejects the length before reading it, so that the length is the ONLY thing
    wrong with the image. Returns the previous length.
    """
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)
    entry = find_image(buf, slot)
    was = _u64(buf, entry + E_LENGTH)
    if was == 0:
        raise ValueError(f"{slot} BL1 length is already zero; that is not a mutation")
    _put_u64(buf, entry + E_LENGTH, 0)
    rehash_image(buf, slot, entry)
    reseal(buf, slot)
    # check_toc is kept on: everything except the zero length must still be valid,
    # and verify_sealed's own image-digest check would catch a stale body hash.
    verify_sealed(buf, slot)
    return was


def retype_bl1_image(buf: bytearray, slot: str,
                     new_type: int = IMAGE_TYPE_SEP_BL2) -> int:
    """Relabel the BL1 TOC entry, so the slot declares no SEP_BL1 image at all.

    ``validate_manifest_payload`` sets ``bl1_found`` only for an entry whose
    ``type`` is ``IMAGE_TYPE_SEP_BL1`` and refuses the slot with ``NO_BL1_IMAGE``
    / ``MANIFEST_ERR_NO_BL1_IMAGE`` when the scan ends without one
    (``manifest_load.c``). Relabelling rewrites ``payload_images[0].type`` to
    SEPBL2, SMCBL1 or SMCBL2, and it is
    the only stimulus that reaches that branch while leaving every other check
    satisfiable: deleting the entry instead would trip the TOC/payload-length
    agreement, and an unknown tag would be refused as BAD_IMAGE_TYPE one check
    earlier.

    The image BODY is untouched, so its digest stays valid and the run reaches the
    BL1 branch rather than dying at IMAGE_HASH_MISMATCH. The label sits inside the
    TOC, which ``payload_hash`` covers, so the slot is re-sealed. Returns the flash
    offset of the relabelled entry.
    """
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)
    if new_type == IMAGE_TYPE_SEP_BL1:
        raise ValueError("new_type is SEP_BL1; that is not a mutation")
    if new_type not in KNOWN_IMAGE_TYPES:
        raise ValueError(
            f"type 0x{new_type:x} is not one of the four is_known_image_type() "
            f"accepts, so the slot would be refused as BAD_IMAGE_TYPE before the "
            f"BL1-presence branch this mutation is aimed at"
        )
    entry = find_image(buf, slot)
    _put_u64(buf, entry + E_TYPE, new_type)
    reseal(buf, slot)
    verify_sealed(buf, slot)
    for e in toc_entries(buf, slot):
        if _u64(buf, e + E_TYPE) == IMAGE_TYPE_SEP_BL1:
            raise AssertionError(
                f"{slot} TOC still declares a SEP_BL1 image after the relabel; the "
                f"write did not land or the payload carries more than one"
            )
    return entry


# Bytes of the second image this module inserts. 4-byte aligned and non-zero, the
# two shapes validate_manifest_payload demands of every entry (manifest_load.c).
LEAD_IMAGE_LEN = 256


def insert_leading_image(buf: bytearray, slot: str,
                         lead_type: int = IMAGE_TYPE_SEP_BL2) -> dict:
    """Put a second image ahead of SEP_BL1, so BL1 is no longer TOC entry 0.

    The position-independence stimulus. Reordering the ``payload_images`` list a
    packer config declares is the usual form; this image declares exactly
    ONE image, the BL1 (``image_count`` is 1 in ``secure_boot.bin``), so there is
    nothing to permute and the second image has to be created. What is preserved is
    the property under test -- the ROM must locate SEP_BL1 by TYPE rather than by
    position, both in ``validate_manifest_payload`` and again in
    ``find_toc_entry`` at handoff (``rom_handoff.c``) -- and inserting rather than
    permuting makes the test stronger, because index 0 now holds an image that is
    NOT the BL1.

    The transformation, all of it inside the packed bytes:

      * ``image_count`` 1 -> 2, which moves the start of the image region from
        ``toc_region_bytes(1)`` to ``toc_region_bytes(2)``;
      * entry 0 becomes ``lead_type`` at the new region start, its body a real
        byte range taken from the head of the BL1 image so its digest is genuine
        content and differs from BL1's;
      * entry 1 is the original BL1 entry with its ``offset`` moved to just past
        the lead image -- ``load_addr``, ``entry_point``, ``length`` and ``type``
        untouched, so the only thing this changes about BL1 is where it sits;
      * the BL1 body is MOVED, not copied, and its old range is zeroed. That is
        what makes ``COPY_SRC=`` (``rom_handoff.c``) independent evidence: the ROM
        can only print the new address if it read entry 1's offset;
      * ``payload_hashed_length`` follows the TOC region, so ``payload_hash``
        still covers the whole TOC and neither entry's metadata is left
        unauthenticated.

    ``payload_length`` and the TOC header's copy of it are untouched, so the
    TOC/manifest agreement ``validate_manifest_payload`` enforces still holds and
    the DMA moves the same number of bytes. Returns the resulting geometry.

    TWO ROM COMPARISONS THIS LAYOUT DEPENDS ON BEING NON-STRICT, named because a
    future tightening of either would look like a broken helper rather than a ROM
    change. The images are packed end to end, so both bounds are hit exactly: the
    ascending-order check is ``off < prev_end`` (``manifest_load.c``), which
    accepts ``off == prev_end``, and the pairwise overlap check is
    ``off < b_end && b_off < end``, whose half-open interval accepts an image
    starting exactly where the previous one ends. Padding the images apart would
    avoid the dependency, but it would also stop the layout from exercising the
    adjacency a real multi-image payload has.
    """
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)
    if lead_type == IMAGE_TYPE_SEP_BL1:
        raise ValueError(
            "lead_type is SEP_BL1; entry 0 must NOT be the BL1 or the ROM could "
            "satisfy the handoff from position 0 and the testcase would prove "
            "nothing about position independence"
        )
    if lead_type not in KNOWN_IMAGE_TYPES:
        raise ValueError(
            f"type 0x{lead_type:x} is not one of the four is_known_image_type() "
            f"accepts; the slot would be refused as BAD_IMAGE_TYPE"
        )

    p = payload_base(buf, slot)
    p_len = manifest_payload_length(buf, slot)
    entries = toc_entries(buf, slot)
    if len(entries) != 1:
        raise AssertionError(
            f"{slot} TOC holds {len(entries)} images; this helper turns the "
            f"single-image payload into a two-image one and has no defined "
            f"meaning for any other starting shape"
        )
    bl1 = entries[0]
    if _u64(buf, bl1 + E_TYPE) != IMAGE_TYPE_SEP_BL1:
        raise AssertionError(
            f"{slot} TOC entry 0 is type 0x{_u64(buf, bl1 + E_TYPE):x}, not "
            f"SEP_BL1: the starting image is not the one this helper assumes"
        )

    bl1_meta = bytes(buf[bl1:bl1 + TOC_ENTRY_SIZE])
    bl1_off = _u64(buf, bl1 + E_OFFSET)
    bl1_len = _u64(buf, bl1 + E_LENGTH)
    bl1_body = read_bytes(buf, p + bl1_off, bl1_len)

    if bl1_len < LEAD_IMAGE_LEN:
        raise AssertionError(
            f"{slot} BL1 image is {bl1_len} bytes, shorter than the {LEAD_IMAGE_LEN} "
            f"the lead image borrows from it"
        )

    region = toc_region_bytes(2)
    lead_off = region
    new_bl1_off = lead_off + LEAD_IMAGE_LEN
    if new_bl1_off + bl1_len > p_len:
        raise AssertionError(
            f"a second image does not fit: TOC region {region} + lead "
            f"{LEAD_IMAGE_LEN} + BL1 {bl1_len} exceeds payload_length {p_len}"
        )

    # Clear the whole image region first, so no stale copy of BL1 survives at its
    # old offset. Those bytes are outside every entry and the ROM zeroes them
    # anyway; doing it here makes "this payload holds exactly two images" a
    # property of the artefact rather than of the ROM's cleanup.
    buf[p + region:p + p_len] = bytes(p_len - region)

    _put_u64(buf, p + TOC_OFF_IMAGE_COUNT, 2)
    e0 = p + TOC_HDR_SIZE
    e1 = e0 + TOC_ENTRY_SIZE
    buf[e0:e0 + TOC_ENTRY_SIZE] = bl1_meta
    buf[e1:e1 + TOC_ENTRY_SIZE] = bl1_meta
    _put_u64(buf, e0 + E_TYPE, lead_type)
    _put_u64(buf, e0 + E_OFFSET, lead_off)
    _put_u64(buf, e0 + E_LENGTH, LEAD_IMAGE_LEN)
    # The lead entry is copied from BL1's, so clear the two fields that would
    # otherwise claim BL1's ICCM window for a second image. The ROM validates
    # neither for a non-SEP_BL1 type (check_bl1_image runs only on the BL1 arm),
    # so they are inert today -- but a payload declaring two images at one load
    # address is not what this stimulus means, and would become a real conflict if
    # the ROM ever loaded BL2.
    _put_u64(buf, e0 + E_LOAD_ADDR, 0)
    _put_u64(buf, e0 + E_ENTRY_POINT, 0)
    _put_u64(buf, e1 + E_OFFSET, new_bl1_off)

    buf[p + lead_off:p + lead_off + LEAD_IMAGE_LEN] = bl1_body[:LEAD_IMAGE_LEN]
    buf[p + new_bl1_off:p + new_bl1_off + bl1_len] = bl1_body

    rehash_image(buf, slot, e0)
    rehash_image(buf, slot, e1)
    _put_u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_HASHED_LEN, region)
    reseal(buf, slot)
    verify_sealed(buf, slot)

    after = toc_entries(buf, slot)
    if len(after) != 2 or _u64(buf, after[0] + E_TYPE) == IMAGE_TYPE_SEP_BL1:
        raise AssertionError(
            f"{slot} TOC is not two images with a non-BL1 first entry after the "
            f"insert: types "
            f"{[hex(_u64(buf, e + E_TYPE)) for e in after]}"
        )
    if find_image(buf, slot) != after[1]:
        raise AssertionError(f"{slot} SEP_BL1 did not end up at TOC index 1")
    return {
        "toc_region": region,
        "lead_offset": lead_off,
        "lead_length": LEAD_IMAGE_LEN,
        "lead_type": lead_type,
        "bl1_offset_before": bl1_off,
        "bl1_offset_after": new_bl1_off,
        "bl1_length": bl1_len,
        "payload_hashed_length": region,
    }


def bl1_sram_source(buf, slot: str) -> int:
    """SRAM address the ROM will print as ``COPY_SRC=`` for this slot's BL1.

    ``rom_handoff_bl1`` copies from ``(uint8_t *)toc + bl1->offset``
    (``rom_handoff.c``), and the TOC is at ``manifest_payload_address()``, which
    for the SPI path resolves to the SRAM manifest base plus the manifest's own
    ``payload_offset`` (``manifest_load.c``: the offset is kept relative to the
    manifest, so no adjustment is applied after the DMA). The manifest is DMA'd to
    ``SRAM_BASE``. Reproducing that here is what lets a testcase assert the ROM
    read the BL1 entry's offset rather than assuming image 0.
    """
    base = mm.slot_base(slot)
    p_off = int.from_bytes(bytes(buf[base + OFF_BOOT_PAYLOAD_OFFSET:
                                     base + OFF_BOOT_PAYLOAD_OFFSET + 8]),
                           "little", signed=True)
    return SEP_SRAM_BASE + p_off + bl1_field(buf, slot, E_OFFSET)


def corrupt_ciphertext(buf: bytearray, slot: str, *, block: int = 0,
                       byte_index: int = 0, mask: int = 0x01) -> tuple[int, int]:
    """Flip a bit of the ENCRYPTED payload so the plaintext TOC magic cannot survive.

    AES-CBC decryption never reports an error for wrong input --
    it is a permutation, so any ciphertext decrypts to something -- and the ROM's
    own ``aes128cbc_decrypt`` only fails on a bad length or an engine alert
    (``aes_driver.c``). The failure therefore has to surface
    DOWNSTREAM, at the TOC identifier check (``manifest_load.c``): the encrypted
    payload is corrupted so the decrypted plaintext does not match the TOC magic.

    Corrupting block 0 is deliberate: in CBC, ``P0 = D(C0) XOR IV``, so altering
    ``C0`` randomises the whole of plaintext block 0 -- the 16 bytes that begin with
    the ``PTOC`` identifier. The manifest is re-sealed afterwards because
    ``payload_hash`` covers the CIPHERTEXT and is verified before decryption
    (``manifest_crypto.c``); without the re-seal the ROM would stop at
    ``PLD_HASH_MISMATCH`` and never call the decrypt path at all.

    Returns ``(flash_offset, new_byte)``.
    """
    if not is_encrypted(buf, slot):
        raise AssertionError(
            f"{slot} does not have the encrypted_payload flag set; corrupting its "
            f"payload would not exercise decryption"
        )
    verify_sealed(buf, slot, check_toc=False)
    verify_signing_key(buf, slot)
    p = payload_base(buf, slot)
    at = p + block * 16 + byte_index
    before = buf[at]
    buf[at] = before ^ mask
    reseal(buf, slot)
    verify_sealed(buf, slot, check_toc=False)
    return at, buf[at]
