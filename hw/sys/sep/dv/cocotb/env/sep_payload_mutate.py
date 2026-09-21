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

from env import sep_aes128cbc as aes
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
TOC_OFF_MAJOR_VERSION = 4       # uint16 in the header
TOC_OFF_MINOR_VERSION = 6       # uint16 in the header
TOC_OFF_PAYLOAD_LENGTH = 8      # uint64 in the header
TOC_OFF_IMAGE_COUNT = 16        # uint64 in the header

# manifest.h -- the only major version validate_manifest_payload accepts.
TOC_MAJOR_VERSION = 1
# manifest_load.c -- image_count must satisfy 0 < n <= 256.
TOC_MAX_IMAGE_COUNT = 256

# AES parameters of the encrypted image, verbatim from
# ``bootrom/prod/configs/encrypted_boot_test.yaml``. The DERIVED key is what the
# cipher takes; the ROM reaches the same 16 bytes by running
# ``kbkdf_hmac_sha256`` over the CLASS_KEY fuse and the manifest's
# ``encryption_kdf_input`` (``manifest_crypto.c``), which is why a testcase using
# these must also preload the matching fuse image.
ENC_DERIVED_KEY = bytes.fromhex("a6a3a5b9ae7a9e141484ab2ba268cb41")
ENC_IV = bytes.fromhex("00112233445566778899aabbccddeeff")

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
def set_payload_hashed_length(buf: bytearray, slot: str, value: int) -> int:
    """Set ``payload_hashed_length`` past its bound, so the slot is refused.

    ``validate_manifest_header`` (``manifest_load.c``) demands
    ``0 < payload_hashed_length <= payload_length`` and echoes the offending value
    as ``PAYLOAD_HASHED_LEN_BAD=``, then returns ``MANIFEST_ERR_BAD_LENGTH``. Both
    out-of-bound classes are reachable and they mean different things:

      * ``value == 0`` asks the ROM to skip the payload digest entirely --
        ``verify_payload_hash`` returns OK for a zero length, which is the hole the
        bound exists to close;
      * ``value > payload_length`` declares a hashed region larger than the payload
        that exists, which is the malformed-length class.

    The field sits at offset 584, INSIDE the TBS (``manifest.h``), so
    ``manifest_hash`` is recomputed. The signature is deliberately NOT renewed: the
    bound is checked in ``validate_manifest_header``, upstream of both
    ``manifest_check_integrity`` and ``rsa_3072_verify``, so the stale signature is
    never examined. Re-hashing anyway is what keeps the declared length the only
    defect rather than one of two.

    ``verify_sealed`` cannot run afterwards -- it reproduces the very bound this
    breaks -- so the anchoring pass runs on the untouched slot first. Returns the
    previous value.
    """
    verify_sealed(buf, slot)
    base = mm.slot_base(slot)
    was = payload_hashed_length(buf, slot)
    p_len = manifest_payload_length(buf, slot)
    if not 0 <= value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("payload_hashed_length is 64 bits")
    if value == was:
        raise ValueError(
            f"{slot} payload_hashed_length is already {value}; that is not a mutation"
        )
    if 0 < value <= p_len:
        raise ValueError(
            f"payload_hashed_length {value} satisfies 0 < value <= payload_length "
            f"({p_len}), so validate_manifest_header would ACCEPT it; this mutator "
            f"exists to violate that bound"
        )
    _put_u64(buf, base + OFF_PAYLOAD_HASHED_LEN, value)
    mm.rehash(buf, slot)
    if payload_hashed_length(buf, slot) != value:
        raise AssertionError(
            f"{slot} payload_hashed_length is {payload_hashed_length(buf, slot)} "
            f"after the write, expected {value}; the mutation did not land"
        )
    return was


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


# ── TOC header mutations, plaintext or encrypted ─────────────────────────────
def toc_plaintext(buf, slot: str) -> bytes:
    """The payload bytes ``validate_manifest_payload`` will actually parse.

    For a plaintext slot that is the payload itself. For an encrypted one the
    stored bytes are ciphertext and the ROM only reaches the TOC after
    ``decrypt_payload`` (``manifest_load.c`` states the ordering: the TOC is read
    LAST because an encrypted payload's TOC is itself ciphertext), so the same
    view has to be obtained here by decrypting. ``verify_roundtrip`` anchors that
    decryption against the packer's own bytes.

    WHY ``payload_hashed_length`` IS THE RIGHT CIPHERTEXT LENGTH, even though the
    ROM hands ``payload_length`` to the AES engine (``manifest_crypto.c``). For an
    ENCRYPTED slot the two are required to be equal: ``validate_manifest_header``
    (``manifest_load.c``) refuses ``h_len != p_len`` on an encrypted payload as
    ``ENC_HASHED_LEN_PARTIAL``. So on any image the ROM can accept the two reads
    name the same bytes, and an image where they differ is refused before the TOC
    is parsed at all, so this view would never be consulted for it.
    """
    p = payload_base(buf, slot)
    if not is_encrypted(buf, slot):
        return read_bytes(buf, p, manifest_payload_length(buf, slot))
    ct = read_bytes(buf, p, payload_hashed_length(buf, slot))
    return aes.verify_roundtrip(ENC_DERIVED_KEY, ENC_IV, ct)


def edit_toc(buf: bytearray, slot: str, mutate, *,
             post_check_toc: bool = False,
             new_hashed_length: int | None = None) -> None:
    """Apply ``mutate`` to the PLAINTEXT payload view and re-seal the slot.

    The single path by which every TOC mutation in this module reaches the packed
    bytes, for both payload kinds:

      * plaintext slot -- ``mutate`` edits the flash bytes themselves, written
        back in place;
      * encrypted slot -- the payload is decrypted, ``mutate`` edits the recovered
        plaintext, and the whole payload is re-encrypted. CBC chains forward, so
        every block from the edited one onwards changes and re-encrypting the
        entire payload is the only correct form; ``mutate`` must not change the
        plaintext LENGTH, or the ciphertext length and its PKCS#7 padding move.

    ``mutate`` receives the plaintext as a ``bytearray`` and edits it in place. It
    sees image bodies as well as TOC metadata, which is what lets a mutator that
    relocates or resizes an image recompute that image's digest over the bytes the
    ROM will actually hash.

    Re-sealing is obligatory either way. ``payload_hash`` covers the stored bytes
    (``manifest_crypto.c`` verifies it over the CIPHERTEXT, before decryption), so
    an un-resealed edit dies at ``PLD_HASH_MISMATCH`` and the check under test is
    never reached. ``new_hashed_length`` is applied between the payload write and
    the re-seal, for a mutator that grows the TOC region and must extend
    ``payload_hash`` to keep the new metadata authenticated.

    ``post_check_toc`` grades the result with :func:`verify_sealed`'s TOC arm. It
    is off by default because an encrypted payload has no offline TOC to parse and
    because some mutations deliberately produce a TOC that arm cannot enumerate.
    """
    verify_sealed(buf, slot, check_toc=not is_encrypted(buf, slot))
    verify_signing_key(buf, slot)

    p = payload_base(buf, slot)
    plain = bytearray(toc_plaintext(buf, slot))
    if bytes(plain[:4]) != TOC_MAGIC:
        raise AssertionError(
            f"{slot} payload does not start with {TOC_MAGIC!r} "
            f"(got {bytes(plain[:4])!r}); the bytes this mutation is about to edit "
            f"are not a TOC header"
        )
    before = bytes(plain)
    mutate(plain)
    if len(plain) != len(before):
        raise AssertionError(
            f"the mutation changed the {slot} plaintext payload from {len(before)} "
            f"to {len(plain)} bytes; every bound the ROM checks is computed from the "
            f"declared payload_length, which this helper does not move"
        )

    if is_encrypted(buf, slot):
        ct = aes.encrypt(ENC_DERIVED_KEY, ENC_IV, bytes(plain))
        stored = payload_hashed_length(buf, slot)
        if len(ct) != stored:
            raise AssertionError(
                f"re-encrypting {slot} produced {len(ct)} bytes but the manifest "
                f"declares payload_hashed_length {stored}; a length change here "
                f"would move every bound the ROM checks"
            )
        buf[p:p + len(ct)] = ct
    else:
        if p + len(plain) > len(buf):
            raise AssertionError(
                f"{slot} payload runs to {p + len(plain)} but the flash image is "
                f"{len(buf)} bytes; writing the plaintext view back would EXTEND the "
                f"artefact instead of editing it"
            )
        buf[p:p + len(plain)] = plain

    if new_hashed_length is not None:
        _put_u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_HASHED_LEN, new_hashed_length)

    reseal(buf, slot)
    verify_sealed(buf, slot, check_toc=post_check_toc)


def _edit_toc_header(buf: bytearray, slot: str, off: int, size: int,
                     value: int) -> int:
    """Write one TOC header field in the PLAINTEXT view and re-seal the slot.

    A thin wrapper over :func:`edit_toc`; see there for how the two payload kinds
    are handled and why the re-seal is obligatory. Returns the previous value of
    the field.

    The post-mutation TOC arm is off for BOTH kinds, and every caller needs it off
    except one. Encrypted: the stored bytes are ciphertext, so there is no TOC to
    parse either way. Plaintext image_count: the mutated count makes toc_entries()
    refuse to enumerate, which is the point of the mutation rather than a fault.
    Plaintext payload_length: :func:`verify_sealed` refuses a TOC whose
    payload_length disagrees with the manifest's, which is exactly what that mutator
    plants, so the arm MUST stay off for it. Plaintext version_major is the only
    caller the arm would pass, and it is turned off there too so that one
    post-mutation call covers every caller.
    """
    was = int.from_bytes(bytes(toc_plaintext(buf, slot)[off:off + size]), "little")

    def _write(plain: bytearray) -> None:
        plain[off:off + size] = int(value).to_bytes(size, "little")

    edit_toc(buf, slot, _write)

    now = int.from_bytes(bytes(toc_plaintext(buf, slot)[off:off + size]), "little")
    if now != value:
        raise AssertionError(
            f"{slot} TOC field at payload offset {off} reads {now} after the write, "
            f"expected {value}; the mutation did not land"
        )
    return was


def set_toc_version_major(buf: bytearray, slot: str, value: int) -> int:
    """Declare a TOC major version the ROM must refuse.

    ``validate_manifest_payload`` (``manifest_load.c``) requires
    ``toc->major_version == TOC_MAJOR_VERSION`` exactly and returns
    ``MANIFEST_ERR_BAD_TOC_VERSION`` otherwise. The arm prints NO console token of
    its own, so the error code is the whole of the ROM-side attribution -- which is
    why the callers pair it with device-side evidence that the planted bytes were
    the ones served.

    The field is a ``uint16`` at offset 4 of the TOC header. Returns the previous
    value.
    """
    if not 0 <= value <= 0xFFFF:
        raise ValueError("toc_header.major_version is 16 bits")
    if value == TOC_MAJOR_VERSION:
        raise ValueError(
            f"major_version {value} is the version the ROM ACCEPTS; this mutator "
            f"exists to violate that equality"
        )
    return _edit_toc_header(buf, slot, TOC_OFF_MAJOR_VERSION, 2, value)


def set_toc_image_count(buf: bytearray, slot: str, value: int) -> int:
    """Declare an image count outside ``0 < n <= 256``.

    ``validate_manifest_payload`` (``manifest_load.c``) refuses both arms with
    ``MANIFEST_ERR_TOC_COUNT``, and they close different holes: ``0`` is a TOC that
    declares no images at all, so every per-image check below is skipped and the
    payload is accepted without a BL1; ``> 256`` is the overlarge count whose TOC
    region would run past the payload the DMA actually staged.

    Both arms are refused BEFORE the ``TOC_REGION_OOB`` bound that follows them, so
    a count just over the limit produces the count verdict rather than the region
    one -- which is what keeps this stimulus attributable.

    LIMIT WORTH KNOWING: the ROM truncates the ``uint64`` field to 32 bits
    (``uint32_t n = (uint32_t)toc->image_count``), so a value whose low 32 bits
    land inside the legal range is ACCEPTED however large the 64-bit number is.
    This mutator refuses such a value rather than planting a stimulus that would
    not reach the check. Returns the previous value.
    """
    if not 0 <= value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("toc_header.image_count is 64 bits")
    truncated = value & 0xFFFF_FFFF
    if 0 < truncated <= TOC_MAX_IMAGE_COUNT:
        raise ValueError(
            f"image_count {value} truncates to {truncated}, which satisfies "
            f"0 < n <= {TOC_MAX_IMAGE_COUNT}, so validate_manifest_payload would "
            f"ACCEPT it; this mutator exists to violate that bound"
        )
    return _edit_toc_header(buf, slot, TOC_OFF_IMAGE_COUNT, 8, value)


def set_toc_payload_length(buf: bytearray, slot: str, value: int) -> int:
    """Declare a TOC payload_length that contradicts the manifest's.

    ``validate_manifest_payload`` (``manifest_load.c``) cross-checks the TOC's copy
    of the payload length against the manifest's, echoes the offending value as
    ``TOC_PLEN_MISMATCH=`` and returns ``MANIFEST_ERR_BAD_LENGTH``. The rule differs
    by payload kind, and this mutator enforces the same distinction the ROM does::

        plaintext -- the two describe the same bytes: toc_p_len != p_len is bad
        encrypted -- the manifest counts CIPHERTEXT and the TOC counts plaintext,
                     so the manifest may legitimately run up to one AES block ahead:
                     toc_p_len > p_len, or p_len - toc_p_len > BLOCK, is bad

    The arm sits in the TOC HEADER stage, above the per-image loop, so a value
    planted here is evaluated before any image offset or length is looked at. That
    ordering is what keeps this stimulus separable from the per-image bound arms.

    Refuses a value the ROM would ACCEPT, so a row cannot silently fall through to
    a later check and report this arm's verdict. Returns the previous value.
    """
    if not 0 <= value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("toc_header.payload_length is 64 bits")
    p_len = manifest_payload_length(buf, slot)
    if is_encrypted(buf, slot):
        bad = value > p_len or p_len - value > aes.BLOCK_BYTES
        rule = (f"toc_payload_length > {p_len} or {p_len} - toc_payload_length > "
                f"{aes.BLOCK_BYTES}")
    else:
        bad = value != p_len
        rule = f"toc_payload_length != {p_len}"
    if not bad:
        raise ValueError(
            f"toc payload_length {value} satisfies the ROM's agreement rule for a "
            f"{'n encrypted' if is_encrypted(buf, slot) else ' plaintext'} payload "
            f"({rule}), so validate_manifest_payload would ACCEPT it; this mutator "
            f"exists to violate that agreement"
        )
    return _edit_toc_header(buf, slot, TOC_OFF_PAYLOAD_LENGTH, 8, value)


# ── TOC ENTRY mutations, plaintext or encrypted ──────────────────────────────
# manifest_load.c -- every image length must be a multiple of this, checked as
# ``(len & 3u) != 0``.
TOC_IMAGE_LENGTH_ALIGN = 4


def toc_entry_at(index: int) -> int:
    """Payload-relative offset of TOC entry ``index``."""
    return TOC_HDR_SIZE + index * TOC_ENTRY_SIZE


def _plain_u64(plain, at: int) -> int:
    return int.from_bytes(bytes(plain[at:at + 8]), "little")


def _plain_put_u64(plain: bytearray, at: int, value: int) -> None:
    plain[at:at + 8] = int(value).to_bytes(8, "little")


def _plain_rehash_entry(plain: bytearray, entry: int) -> None:
    """Recompute one TOC entry's digest over the body it now declares."""
    off, ln = _plain_u64(plain, entry + E_OFFSET), _plain_u64(plain, entry + E_LENGTH)
    body = bytes(plain[off:off + ln])
    if len(body) != ln:
        raise AssertionError(
            f"TOC entry at payload offset {entry} declares {ln} bytes at {off}, "
            f"but only {len(body)} are inside the payload; the digest would cover "
            f"a different range from the one the ROM will hash"
        )
    plain[entry + E_HASH:entry + E_HASH + 32] = hashlib.sha256(body).digest()


def set_toc_entry_length(buf: bytearray, slot: str, index: int, value: int) -> int:
    """Declare an image length that is not 4-byte aligned, so the slot is refused.

    ``validate_manifest_payload`` (``manifest_load.c``) grades each TOC entry in a
    fixed order, and this mutator targets the alignment arm::

        end > p_len      -> MANIFEST_ERR_IMAGE_OOB      (SILENT)
        off < prev_end   -> IMAGE_ORDER_BAD idx= + MANIFEST_ERR_IMAGE_OVERLAP
        length == 0      -> IMAGE_LEN_ZERO  idx= + MANIFEST_ERR_IMAGE_OOB
        (len & 3) != 0   -> IMAGE_LEN_ALIGN idx= + MANIFEST_ERR_IMAGE_OOB

    THE ERROR CODE ALONE CANNOT ATTRIBUTE THIS ARM. The bounds arm above it
    returns the SAME ``MANIFEST_ERR_IMAGE_OOB`` and prints nothing, so a length
    that overran the payload would produce this mutator's error code by a different
    check entirely. Two things stop that: the caller requires the
    ``IMAGE_LEN_ALIGN idx=`` token, which only this arm prints, and the guard below
    refuses any value that would reach the bounds arm first.

    The entry's digest is recomputed over the newly declared range, so the image
    still hashes correctly and alignment is the ONLY rule the slot violates.
    Returns the previous length.
    """
    if not 0 <= value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("toc_entry.length is 64 bits")
    if value == 0:
        raise ValueError(
            "length 0 is the IMAGE_LEN_ZERO arm, a different check with its own "
            "token; this mutator exists to violate the alignment rule"
        )
    if value % TOC_IMAGE_LENGTH_ALIGN == 0:
        raise ValueError(
            f"length {value} is {TOC_IMAGE_LENGTH_ALIGN}-byte aligned, which the ROM "
            f"ACCEPTS; this mutator exists to violate that alignment"
        )
    entry = toc_entry_at(index)
    was = 0

    def _write(plain: bytearray) -> None:
        nonlocal was
        count = _plain_u64(plain, TOC_OFF_IMAGE_COUNT)
        if not index < count:
            raise AssertionError(
                f"{slot} TOC declares {count} images; entry {index} does not exist"
            )
        off = _plain_u64(plain, entry + E_OFFSET)
        was = _plain_u64(plain, entry + E_LENGTH)
        # The bounds arm runs BEFORE the alignment arm and returns the same error
        # code without printing, so a value that overran the payload would swap the
        # check under test for a silent one and the row would still see its code.
        limit = min(manifest_payload_length(buf, slot), len(plain))
        if off + value > limit:
            raise AssertionError(
                f"image {index} at offset {off} with length {value} ends at "
                f"{off + value}, past the {limit} bytes the ROM bounds it to; "
                f"MANIFEST_ERR_IMAGE_OOB would be returned by the SILENT bounds arm "
                f"instead of by the alignment arm this mutator targets"
            )
        _plain_put_u64(plain, entry + E_LENGTH, value)
        _plain_rehash_entry(plain, entry)

    edit_toc(buf, slot, _write, post_check_toc=not is_encrypted(buf, slot))
    return was


def toc_entry_lower_bound(buf, slot: str, index: int) -> int:
    """The lowest offset ``validate_manifest_payload`` will accept for image ``index``.

    The ROM seeds ``prev_end`` at the TOC region and then carries each accepted
    image's end forward, so the bound an entry must clear is the TOC region for
    entry 0 and the previous image's end for every entry after it. Exposed because
    a testcase that plants a violating offset has to state the bound it violates,
    and computing it from the artefact is the only way that statement stays true
    when the shipped payload's geometry changes.
    """
    plain = toc_plaintext(buf, slot)
    count = _plain_u64(plain, TOC_OFF_IMAGE_COUNT)
    if not 0 <= index < count:
        raise AssertionError(
            f"{slot} TOC declares {count} images; entry {index} does not exist"
        )
    if index == 0:
        return toc_region_bytes(count)
    prev = toc_entry_at(index - 1)
    return _plain_u64(plain, prev + E_OFFSET) + _plain_u64(plain, prev + E_LENGTH)


def set_toc_entry_offset(buf: bytearray, slot: str, index: int, value: int) -> int:
    """Declare an image body starting below the region it is allowed to occupy.

    ``validate_manifest_payload`` (``manifest_load.c``) requires every image body to
    begin at or after ``prev_end`` -- the TOC region for entry 0, the previous
    image's end afterwards -- and refuses the rest as
    ``IMAGE_ORDER_BAD idx=`` + ``MANIFEST_ERR_IMAGE_OVERLAP``. This mutator targets
    the ENTRY-0 half of that rule, where the bound being violated is the TOC region
    itself: the declared body would overlap the metadata the ROM is parsing.

    THE ARM ABOVE IT IS SILENT AND MUST NOT BE REACHED. ``end > p_len`` returns
    ``MANIFEST_ERR_IMAGE_OOB`` without printing, so an offset that pushed the body
    past the payload would produce a different verdict with no token to say so. The
    guard below refuses any such value rather than planting it.

    The entry's digest is recomputed over the range it now declares, so the image
    still hashes correctly and the ordering bound is the ONLY rule the slot
    violates. ``image_count`` and the TOC's ``payload_length`` are untouched, so
    neither the TOC-region bound nor the TOC/manifest agreement can pre-empt this
    arm. Returns the previous offset.
    """
    if not 0 <= value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("toc_entry.offset is 64 bits")
    entry = toc_entry_at(index)
    bound = toc_entry_lower_bound(buf, slot, index)
    if value >= bound:
        raise ValueError(
            f"offset {value} is at or above the lowest offset the ROM accepts for "
            f"image {index} ({bound}), so validate_manifest_payload would ACCEPT the "
            f"ordering of this entry; this mutator exists to violate that bound"
        )
    was = 0

    def _write(plain: bytearray) -> None:
        nonlocal was
        was = _plain_u64(plain, entry + E_OFFSET)
        ln = _plain_u64(plain, entry + E_LENGTH)
        end = value + ln
        # The SILENT bounds arm runs BEFORE the ordering arm, so a body that ran off
        # the payload would swap the announced check under test for an unannounced
        # one and the row would have no token to attribute its verdict to.
        limit = min(manifest_payload_length(buf, slot), len(plain))
        if end < value or end > limit:
            raise AssertionError(
                f"image {index} at offset {value} with length {ln} ends at {end}, "
                f"outside the {limit} bytes the ROM bounds it to; the SILENT "
                f"MANIFEST_ERR_IMAGE_OOB arm would fire instead of the ordering arm "
                f"this mutator targets"
            )
        _plain_put_u64(plain, entry + E_OFFSET, value)
        _plain_rehash_entry(plain, entry)

    edit_toc(buf, slot, _write, post_check_toc=not is_encrypted(buf, slot))
    return was


def make_images_out_of_order(buf: bytearray, slot: str, *, second_offset: int,
                             second_length: int,
                             second_type: int = IMAGE_TYPE_SEP_BL2) -> dict:
    """Add a second image BELOW the first, so the TOC is not in ascending order.

    ``validate_manifest_payload`` (``manifest_load.c``) requires image bodies to
    start after the TOC region and to run in strictly ascending order, enforced as
    ``off < prev_end`` with ``prev_end`` seeded at the TOC region and then carrying
    the previous image's end. Entry 1 declaring an offset below entry 0's end
    violates the ascending half, which is the half a two-image payload can reach;
    the same ``if`` also covers "before the TOC region", and the assertions here
    keep entry 0 clear of it so the violation is unambiguously the ordering one.

    The shipped payload declares exactly ONE image, so the second has to be
    created, as in :func:`insert_leading_image`. What differs is the intent: that
    helper builds an ASCENDING two-image layout to prove the ROM finds SEP_BL1 by
    type, and this one builds a DESCENDING pair to make the ROM refuse it.

    The transformation, all inside the payload:

      * ``image_count`` 1 -> 2, moving the image region's lower bound from
        ``toc_region_bytes(1)`` to ``toc_region_bytes(2)``;
      * entry 0 keeps the SEP_BL1 metadata and body EXACTLY as shipped, so its
        digest stays valid and it passes every per-entry check;
      * entry 1 is a new ``second_type`` image at ``second_offset``, its body taken
        from the head of the BL1 image so the digest covers genuine content, and
        its ``load_addr``/``entry_point`` cleared so it claims no ICCM window.

    ``payload_length`` and the TOC header's copy of it are untouched, so the
    TOC/manifest agreement still holds and the DMA moves the same bytes. The
    caller passes ``payload_hashed_length`` forward for a plaintext slot, whose
    hash covers only the TOC region and would otherwise leave the new entry
    unauthenticated. Returns the resulting geometry.
    """
    region = toc_region_bytes(2)
    e0, e1 = toc_entry_at(0), toc_entry_at(1)
    if second_type not in KNOWN_IMAGE_TYPES:
        raise ValueError(
            f"type 0x{second_type:x} is not one of the four is_known_image_type() "
            f"accepts; the slot would be refused as BAD_IMAGE_TYPE before the "
            f"ordering check this mutator targets"
        )
    if second_length % TOC_IMAGE_LENGTH_ALIGN != 0 or second_length == 0:
        raise ValueError(
            f"second_length {second_length} is zero or misaligned, which would let "
            f"IMAGE_LEN_ZERO or IMAGE_LEN_ALIGN fire instead of the ordering check"
        )
    geometry: dict = {}

    def _write(plain: bytearray) -> None:
        count = _plain_u64(plain, TOC_OFF_IMAGE_COUNT)
        if count != 1:
            raise AssertionError(
                f"{slot} TOC holds {count} images; this helper turns the "
                f"single-image payload into a two-image one and has no defined "
                f"meaning for any other starting shape"
            )
        if _plain_u64(plain, e0 + E_TYPE) != IMAGE_TYPE_SEP_BL1:
            raise AssertionError(
                f"{slot} TOC entry 0 is type 0x{_plain_u64(plain, e0 + E_TYPE):x}, "
                f"not SEP_BL1: the starting image is not the one this helper assumes"
            )
        off0 = _plain_u64(plain, e0 + E_OFFSET)
        len0 = _plain_u64(plain, e0 + E_LENGTH)
        # Entry 0 must survive every per-entry check, or the ROM stops on entry 0
        # and the ordering violation planted in entry 1 is never evaluated.
        if off0 < region:
            raise AssertionError(
                f"entry 0 starts at {off0}, inside the two-image TOC region "
                f"({region}); it would trip the ordering check itself and the "
                f"violation under test would be attributed to the wrong entry"
            )
        if off0 + len0 > min(manifest_payload_length(buf, slot), len(plain)):
            raise AssertionError(
                f"entry 0 spans {off0}..{off0 + len0}, past the payload; the SILENT "
                f"bounds arm would refuse it before entry 1 is reached"
            )
        if len0 < second_length:
            raise AssertionError(
                f"the BL1 image is {len0} bytes, shorter than the {second_length} "
                f"the second image borrows from it"
            )
        # Entry 1 must reach the ordering check, so it has to clear the bounds arm
        # ahead of it, and it must actually violate the ordering it is planted for.
        if second_offset < region:
            raise AssertionError(
                f"second_offset {second_offset} is inside the TOC region ({region}); "
                f"entry 1's body would overlap the metadata the ROM is parsing"
            )
        if second_offset + second_length > off0:
            raise AssertionError(
                f"the second image ({second_offset}..{second_offset + second_length}) "
                f"runs into entry 0 at {off0}; the payload would hold two overlapping "
                f"bodies rather than one out-of-order pair"
            )
        if not second_offset < off0 + len0:
            raise AssertionError(
                f"second_offset {second_offset} is not below entry 0's end "
                f"({off0 + len0}), so the TOC would be in ascending order and the "
                f"ROM would ACCEPT it"
            )

        _plain_put_u64(plain, TOC_OFF_IMAGE_COUNT, 2)
        plain[e1:e1 + TOC_ENTRY_SIZE] = bytes(plain[e0:e0 + TOC_ENTRY_SIZE])
        _plain_put_u64(plain, e1 + E_TYPE, second_type)
        _plain_put_u64(plain, e1 + E_OFFSET, second_offset)
        _plain_put_u64(plain, e1 + E_LENGTH, second_length)
        # Copied from BL1's entry, so clear the two fields that would otherwise
        # claim BL1's ICCM window for a second image. The ROM validates neither for
        # a non-SEP_BL1 type, so they are inert today, but a payload declaring two
        # images at one load address is not what this stimulus means.
        _plain_put_u64(plain, e1 + E_LOAD_ADDR, 0)
        _plain_put_u64(plain, e1 + E_ENTRY_POINT, 0)
        plain[second_offset:second_offset + second_length] = \
            bytes(plain[off0:off0 + second_length])
        _plain_rehash_entry(plain, e1)
        geometry.update(toc_region=region, first_offset=off0, first_length=len0,
                        second_offset=second_offset, second_length=second_length,
                        second_type=second_type)

    edit_toc(buf, slot, _write,
             post_check_toc=not is_encrypted(buf, slot),
             new_hashed_length=None if is_encrypted(buf, slot) else region)
    geometry["payload_hashed_length"] = payload_hashed_length(buf, slot)
    return geometry


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


# ── payload size ─────────────────────────────────────────────────────────────
# Flash span a manifest slot owns, from the two slot offsets in manifest.h. A
# payload may not grow past the next slot's manifest, and boot_flash.h bounds a
# slot read by the same span (OCH_SEP_TOP_SEP_SRAM_SIZE).
SLOT_FLASH_LIMIT = {
    "primary": mm.BACKUP_MANIFEST_OFFSET,
    "backup": mm.BACKUP_MANIFEST_OFFSET + (mm.BACKUP_MANIFEST_OFFSET
                                           - mm.PRIMARY_MANIFEST_OFFSET),
}


def repack_payload(buf: bytearray, slot: str, payload_length: int, *,
                   bl1_offset: int | None = None) -> dict:
    """Rebuild ``slot``'s payload so it is exactly ``payload_length`` bytes, and boots.

    The payload-size stimulus. The shipped payload is one 1840-byte SEP_BL1 inside
    a 5936-byte region, so a testcase naming any other size has to produce that
    size rather than declare it: ``manifest_src_read`` transfers
    ``payload_length`` bytes off the wire (``manifest_load.c``), so a declared
    length the material does not back would change what the DUT fetches.

    Both copies of the length are written -- the manifest's and the TOC header's --
    because ``validate_manifest_payload`` requires them to agree, and the region is
    zero-filled around the one image so every byte outside it is a known value. The
    ROM zeroes those gaps itself (``explicit_memzero`` in the entry loop), so this
    only makes the artefact match what the ROM will hold.

    ``bl1_offset`` moves the image body, which a payload SMALLER than the shipped
    one requires: the packer leaves BL1 at 4096, past the end of a 4 KiB payload.
    The default keeps the shipped offset whenever the body still fits and otherwise
    packs the body directly behind the TOC region, which is the lowest offset
    ``off < prev_end`` accepts.

    ``payload_hashed_length`` stays at the TOC region, exactly as the packer ships
    it: ``payload_hash`` then covers the TOC header and every entry -- including
    both length fields and the body digest -- and each body is bound by its own
    entry digest. What that leaves unbound is the fill, so nothing the ROM verifies
    depends on the staged copy of it; a caller that needs the whole transfer bound
    by a digest has to widen this field and give the fill content worth hashing.

    Returns the resulting geometry.
    """
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)

    p = payload_base(buf, slot)
    was_len = manifest_payload_length(buf, slot)
    region = toc_region_bytes(1)
    entries = toc_entries(buf, slot)
    if len(entries) != 1:
        raise AssertionError(
            f"{slot} TOC holds {len(entries)} images; this helper repacks the "
            f"single-image payload the packer ships and has no defined meaning "
            f"for any other starting shape"
        )
    bl1 = entries[0]
    if _u64(buf, bl1 + E_TYPE) != IMAGE_TYPE_SEP_BL1:
        raise AssertionError(
            f"{slot} TOC entry 0 is type 0x{_u64(buf, bl1 + E_TYPE):x}, not SEP_BL1"
        )
    if payload_hashed_length(buf, slot) != region:
        raise AssertionError(
            f"{slot} payload_hashed_length is {payload_hashed_length(buf, slot)}, "
            f"not the TOC region {region}; this helper preserves the packer's "
            f"choice and cannot tell which coverage a different value intended"
        )

    bl1_len = _u64(buf, bl1 + E_LENGTH)
    bl1_body = read_bytes(buf, p + _u64(buf, bl1 + E_OFFSET), bl1_len)
    toc_header = read_bytes(buf, p, TOC_HDR_SIZE)
    bl1_meta = read_bytes(buf, bl1, TOC_ENTRY_SIZE)

    if bl1_offset is None:
        shipped = _u64(buf, bl1 + E_OFFSET)
        bl1_offset = shipped if shipped + bl1_len <= payload_length else region
    if bl1_offset < region:
        raise ValueError(
            f"bl1_offset {bl1_offset} is inside the {region}-byte TOC region; "
            f"validate_manifest_payload refuses it as IMAGE_ORDER_BAD"
        )
    if bl1_offset % 8 != 0:
        raise ValueError(
            f"bl1_offset {bl1_offset} is not 8-byte aligned; the ROM refuses it as "
            f"IMAGE_OFF_ALIGN before any bound is evaluated"
        )
    if bl1_offset + bl1_len > payload_length:
        raise ValueError(
            f"a {payload_length}-byte payload cannot hold the {bl1_len}-byte BL1 at "
            f"offset {bl1_offset}: the ROM refuses it as IMAGE_OOB_BOUND, which is "
            f"not the size decision under test"
        )
    if payload_length > 0xFFFF_FFFF:
        raise ValueError("payload_length is read as 32 bits by every consumer")
    limit = SLOT_FLASH_LIMIT[slot]
    if p + payload_length > limit:
        raise ValueError(
            f"a {payload_length}-byte {slot} payload at flash 0x{p:x} would reach "
            f"0x{p + payload_length:x}, past the 0x{limit:x} its slot owns; the "
            f"material would overwrite the next slot and the ROM's own slot bound "
            f"(boot_flash.h) would refuse the read"
        )
    if p + payload_length > len(buf):
        buf.extend(bytes(p + payload_length - len(buf)))

    buf[p:p + payload_length] = bytes(payload_length)
    buf[p:p + TOC_HDR_SIZE] = toc_header
    _put_u64(buf, p + TOC_OFF_PAYLOAD_LENGTH, payload_length)
    _put_u64(buf, p + TOC_OFF_IMAGE_COUNT, 1)
    entry = p + TOC_HDR_SIZE
    buf[entry:entry + TOC_ENTRY_SIZE] = bl1_meta
    _put_u64(buf, entry + E_OFFSET, bl1_offset)
    buf[p + bl1_offset:p + bl1_offset + bl1_len] = bl1_body

    _put_u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_LENGTH, payload_length)
    rehash_image(buf, slot, entry)
    reseal(buf, slot)
    verify_sealed(buf, slot)

    if manifest_payload_length(buf, slot) != payload_length:
        raise AssertionError(
            f"{slot} payload_length is {manifest_payload_length(buf, slot)} after "
            f"the repack, expected {payload_length}"
        )
    return {
        "payload_length_before": was_len,
        "payload_length": payload_length,
        "payload_flash_offset": p,
        "toc_region": region,
        "bl1_offset": bl1_offset,
        "bl1_length": bl1_len,
        "payload_hashed_length": payload_hashed_length(buf, slot),
    }


def declare_payload_length(buf: bytearray, slot: str, payload_length: int) -> int:
    """Declare a payload the destination cannot hold, leaving the slot otherwise sealed.

    The over-capacity stimulus. ``validate_manifest_header`` refuses
    ``payload_offset + payload_length > SEP SRAM size`` with
    ``MANIFEST_ERR_PAYLOAD_TOO_LARGE`` (``manifest_load.c``) before the payload is
    ever fetched, so the material behind the declaration is never read and must
    not be produced: transferring a quarter-megabyte the ROM has already refused
    would cost simulation time and prove nothing.

    Both length fields are written and the slot is re-signed, so the declared size
    is the ONLY thing wrong with it. That matters more here than for a mutation the
    ROM rejects before RSA: a stale signature would also be refused, on the
    failover path, by a slot error that looks the same from the console.

    Returns the previous manifest ``payload_length``.
    """
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)
    was = manifest_payload_length(buf, slot)
    if payload_length <= was:
        raise ValueError(
            f"declared payload_length {payload_length} does not exceed the packed "
            f"{was}; this mutator exists to over-declare"
        )
    if payload_length > 0xFFFF_FFFF:
        raise ValueError(
            "payload_length above 32 bits is refused by the PAYLOAD_LEN_RANGE arm, "
            "which is a different check from the capacity one"
        )
    p = payload_base(buf, slot)
    _put_u64(buf, p + TOC_OFF_PAYLOAD_LENGTH, payload_length)
    _put_u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_LENGTH, payload_length)
    reseal(buf, slot)
    verify_sealed(buf, slot)
    return was


def set_overlapping_payload_offset(buf: bytearray, slot: str, value: int) -> int:
    """Declare a ``payload_offset`` that places the payload inside the manifest header.

    ``validate_manifest_header`` (``manifest_load.c``) refuses
    ``payload_offset < manifest_length`` with ``MANIFEST_ERR_PAYLOAD_OVERLAP``,
    announcing ``PAYLOAD_OVERLAPS_MANIFEST``: the staged payload would be written
    over the header whose fields the ROM is still reading.

    NO RE-SEAL, and that is a property of the layout rather than an omission.
    ``boot_arguments`` sits outside the TBS and outside the bytes ``manifest_hash``
    covers (``manifest.h``: TBS is [0..743], the hash at [1128..1159]), so both stay
    valid and the overlap is the only thing wrong with a genuinely signed slot.

    THE PAYLOAD IS NOT MOVED. The refusal is upstream of the payload fetch, so the
    bytes at the declared offset are never read; relocating material into the
    manifest header would overwrite the very fields this check reads.

    Refuses any value a DIFFERENT arm claims first -- ``payload_offset <= 0`` and a
    misaligned one both return ``MANIFEST_ERR_BAD_LENGTH`` -- and any value the ROM
    would accept. Returns the previous value.
    """
    base = mm.slot_base(slot)
    m_len = mm.manifest_length(buf, slot)
    if value <= 0:
        raise ValueError(
            f"payload_offset {value} is refused by the `p_off <= 0` arm with "
            f"MANIFEST_ERR_BAD_LENGTH, which is not the overlap verdict"
        )
    if value & 7:
        raise ValueError(
            f"payload_offset {value} is not 8-byte aligned, so the PAYLOAD_OFF_ALIGN "
            f"arm fires first and also returns MANIFEST_ERR_BAD_LENGTH"
        )
    if value >= m_len:
        raise ValueError(
            f"payload_offset {value} is at or above {slot}'s manifest_length "
            f"{m_len}, so the payload does not overlap the header and "
            f"validate_manifest_header would ACCEPT it"
        )
    was = int.from_bytes(bytes(buf[base + OFF_BOOT_PAYLOAD_OFFSET:
                                   base + OFF_BOOT_PAYLOAD_OFFSET + 8]),
                         "little", signed=True)
    p_len = manifest_payload_length(buf, slot)
    if value + p_len > SEP_SRAM_SIZE:
        raise ValueError(
            f"payload_offset {value} + payload_length {p_len} is {value + p_len}, "
            f"past the {SEP_SRAM_SIZE}-byte SEP SRAM the capacity arm bounds it to; "
            f"that arm runs BEFORE the overlap one and returns a different code"
        )
    # Prove the slot is fully sealed BEFORE the write, so the overlap is the only
    # thing wrong with it afterwards. This has to happen here rather than in the
    # caller: the ROM refuses the slot UPSTREAM of its own integrity check, so a
    # broken seal would be invisible in the run.
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)

    _put_u64(buf, base + OFF_BOOT_PAYLOAD_OFFSET, value)

    # And prove the write left the seal intact. The claim that boot_arguments sits
    # outside the TBS and outside the bytes manifest_hash covers is what licenses
    # not re-signing; assert it against the real bytes, so a future move of
    # OFF_BOOT_PAYLOAD_OFFSET into the hashed region fails loudly here instead of
    # turning into a signature rejection the run cannot distinguish.
    mm.verify_layout(buf, slot)
    n, _e, _d = load_rsa_private_key()
    tbs = bytes(buf[base:base + mm.TBS_LEN])
    sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
    if not verify_pkcs1v15_sha256(tbs, sig, n):
        raise AssertionError(
            f"{slot} signature no longer verifies after writing payload_offset; the "
            f"field is supposed to sit outside the TBS, so either the offset moved "
            f"or the layout this mutator assumes is wrong"
        )
    return was


def corrupt_toc_entry_hash(buf: bytearray, slot: str, index: int, *,
                           value: bytes = b"\x00" * 32,
                           reseal: bool = False) -> bytes:
    """Replace one TOC entry's image digest and leave the body it covers untouched.

    Corrupting the DIGEST rather than the body is what keeps the stimulus a hash
    stimulus: a modified body changes what ``payload_hash`` covers as well, so the
    two rules below could no longer be told apart.

    ``reseal`` SELECTS WHICH OF THE ROM'S TWO HASH RULES REFUSES THE SLOT. They are
    different checks with different codes, and the packer's geometry is what couples
    them: ``payload_hashed_length`` is the whole TOC region, so the digest field
    lies INSIDE the bytes ``payload_hash`` covers.

      * ``False`` (default) -- ``payload_hash`` is left describing the SHIPPED
        bytes, so ``verify_payload_hash`` (``manifest_crypto.c``) refuses the slot
        with ``PLD_HASH_MISMATCH`` / ``MANIFEST_ERR_PAYLOAD_HASH_MISMATCH``,
        upstream of the per-entry loop and inside ``manifest_crypto_validate``. This
        is the mechanism the reference regression uses: its SPI-preload editor
        rewrites the digest and re-signs nothing. The manifest hash and the
        signature stay valid because ``payload_hash`` sits inside the TBS, so the
        stale digest is the only thing wrong with the slot.
      * ``True`` -- the slot is re-sealed, so ``payload_hash`` covers the planted
        digest and the rejection moves DOWNSTREAM to the per-entry arm,
        ``IMAGE_HASH_MISMATCH idx=`` / ``MANIFEST_ERR_IMAGE_HASH_MISMATCH``
        (``manifest_load.c``). A row wanting that arm must say so explicitly,
        because it is not the reference's rule.

    The non-resealing form is plaintext-only: an encrypted payload's digest field is
    ciphertext, and a raw write there would also corrupt the decryption rather than
    just the hash.

    Returns the bytes stored at the field -- for a re-sealed encrypted payload the
    ciphertext the re-encryption produced -- so a caller can require the device to
    have served exactly them.
    """
    if len(value) != 32:
        raise ValueError("a TOC entry digest is 32 bytes")
    entry = toc_entry_at(index)
    plain_before = bytes(toc_plaintext(buf, slot))
    count = int.from_bytes(plain_before[TOC_OFF_IMAGE_COUNT:
                                        TOC_OFF_IMAGE_COUNT + 8], "little")
    if not 0 <= index < count:
        raise ValueError(
            f"{slot} TOC declares {count} images, so entry {index} does not exist "
            f"and no hash arm would ever reach it"
        )
    was = plain_before[entry + E_HASH:entry + E_HASH + 32]
    if was == value:
        raise ValueError(
            f"{slot} TOC entry {index} already carries this digest, so the hash "
            f"comparison would SUCCEED; this mutator exists to violate it"
        )
    body_off = int.from_bytes(plain_before[entry + E_OFFSET:entry + E_OFFSET + 8],
                              "little")
    body_len = int.from_bytes(plain_before[entry + E_LENGTH:entry + E_LENGTH + 8],
                              "little")
    body_before = plain_before[body_off:body_off + body_len]

    if reseal:
        def _write(plain: bytearray) -> None:
            plain[entry + E_HASH:entry + E_HASH + 32] = value

        # verify_sealed's TOC arm recomputes every image digest, which is exactly
        # what this mutation breaks, so it must stay off afterwards.
        edit_toc(buf, slot, _write, post_check_toc=False)
    else:
        if is_encrypted(buf, slot):
            raise ValueError(
                f"{slot} payload is encrypted, so its TOC entry digest is stored as "
                f"ciphertext; a raw write there corrupts the decryption as well as "
                f"the hash. Pass reseal=True, which decrypts, edits and re-encrypts "
                f"-- and aims at the per-entry arm instead"
            )
        # Prove the slot is fully sealed BEFORE the write, so what follows is
        # attributable to this edit and to nothing already wrong with the image.
        verify_sealed(buf, slot)
        verify_signing_key(buf, slot)
        hashed = payload_hashed_length(buf, slot)
        if not entry + E_HASH + 32 <= hashed:
            raise AssertionError(
                f"{slot} payload_hashed_length is {hashed}, which does not reach "
                f"entry {index}'s digest at {entry + E_HASH}..{entry + E_HASH + 32}; "
                f"payload_hash would not cover the edit and verify_payload_hash "
                f"would ACCEPT it, so the non-resealing form proves nothing here"
            )
        p = payload_base(buf, slot)
        buf[p + entry + E_HASH:p + entry + E_HASH + 32] = value

    now = bytes(toc_plaintext(buf, slot)[entry + E_HASH:entry + E_HASH + 32])
    if now != value:
        raise AssertionError(
            f"{slot} TOC entry {index} digest reads {now.hex()} after the write, "
            f"expected {value.hex()}; the mutation did not land"
        )
    # The docstring's claim that only the digest moved, proved rather than asserted
    # in prose: the body the digest covers has to be byte-identical.
    plain_now = bytes(toc_plaintext(buf, slot))
    body_now = plain_now[body_off:body_off + body_len]
    if body_now != body_before:
        raise AssertionError(
            f"{slot} image {index}'s body at payload[{body_off}:{body_off + body_len}] "
            f"changed; this mutator corrupts the DIGEST only, and a changed body "
            f"would make the two hash rules indistinguishable"
        )

    base = mm.slot_base(slot)
    if not reseal:
        # The stale digest must make the ROM's own payload-hash comparison FAIL, and
        # the manifest hash and signature must still verify -- otherwise the slot
        # would be refused for a reason this stimulus did not plant.
        hashed = payload_hashed_length(buf, slot)
        stored_hash = bytes(buf[base + OFF_PAYLOAD_HASH:base + OFF_PAYLOAD_HASH + 32])
        if hashlib.sha256(read_bytes(buf, payload_base(buf, slot), hashed)).digest() \
                == stored_hash:
            raise AssertionError(
                f"{slot} payload_hash still matches sha256(payload[:{hashed}]) after "
                f"the write, so verify_payload_hash would ACCEPT the slot"
            )
        mm.verify_layout(buf, slot)
        n, _e, _d = load_rsa_private_key()
        tbs = bytes(buf[base:base + mm.TBS_LEN])
        sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
        if not verify_pkcs1v15_sha256(tbs, sig, n):
            raise AssertionError(
                f"{slot} signature no longer verifies; payload_hash sits inside the "
                f"TBS and must not have been touched by this write"
            )

    p = payload_base(buf, slot)
    return bytes(buf[p + entry + E_HASH:p + entry + E_HASH + 32])


# ── payload field width limits ────────────────────────────────────────────────
# validate_manifest_header range-checks payload_offset and payload_length at
# their FULL 64-bit width before narrowing either to 32 bits, then re-checks
# their 32-bit sum for wrap. Three arms return MANIFEST_ERR_PAYLOAD_TOO_LARGE and
# one returns MANIFEST_ERR_BAD_LENGTH, so a stimulus aimed at one of them has to
# exclude the others by construction rather than by reading the code:
#
#   payload_offset  > +0x7FFFFFFF or < -0x7FFFFFFF  PAYLOAD_OFF_RANGE, BAD_LENGTH
#   payload_length  > 0xFFFFFFFF                    PAYLOAD_LEN_RANGE, TOO_LARGE
#   (p_off + p_len) wraps uint32                    silent,            TOO_LARGE
#   (p_off + p_len) > SRAM_SIZE                     silent,            TOO_LARGE
PAYLOAD_OFF_RANGE_LIMIT = 0x7FFF_FFFF
PAYLOAD_LEN_RANGE_LIMIT = 0xFFFF_FFFF

# The procedure's payload_offset boundary values. Every one exceeds the positive
# range limit, so all three land on the same arm; the draw is logged and its
# class asserted, so a run says which value it used.
OFF_RANGE_VALUES = (0xFFFF_F000, 0xFFFF_FFFF, 0x8000_0000)


def declare_wrapping_payload_length(buf: bytearray, slot: str) -> dict:
    """Declare the ``payload_length`` whose 32-bit sum with ``payload_offset`` wraps.

    The arithmetic-wrap stimulus, and the one arm of ``validate_manifest_header``
    that prints NOTHING: it returns ``MANIFEST_ERR_PAYLOAD_TOO_LARGE`` from
    ``total < p_off`` after ``total = (uint32_t)p_off + p_len`` has already lost
    the carry (``manifest_load.c``). So the console cannot attribute this arm and
    the stimulus has to exclude its three siblings arithmetically instead:

    * ``PAYLOAD_LEN_RANGE`` cannot claim it, because ``0xFFFFFFFF`` is the largest
      value that arm ACCEPTS -- the test is ``>``, not ``>=``. This is therefore
      also that arm's accept-side boundary, and the token being absent is what
      proves the boundary sits where it is supposed to.
    * the CAPACITY arm cannot claim it, because the wrapped sum is ``p_off - 1``,
      far below SRAM capacity. Asserted below against the real field values, not
      argued: if this held, the two silent arms would be interchangeable.
    * ``PAYLOAD_OFF_RANGE`` and ``PAYLOAD_OFF_ALIGN`` cannot claim it, because
      ``payload_offset`` is left exactly as the packer sealed it.

    A ROM without the wrap test would compute a small ``total``, find it inside
    SRAM, and ACCEPT the slot -- which is the silent arithmetic wrap the row
    exists to refuse. The rejection is therefore the whole result, and the
    material behind the declaration is NOT produced: the refusal precedes the
    payload fetch, so 4 GiB of flash would be neither readable nor read.

    Returns the geometry the wrap decision was made on.
    """
    base = mm.slot_base(slot)
    p_off = int.from_bytes(bytes(buf[base + OFF_BOOT_PAYLOAD_OFFSET:
                                     base + OFF_BOOT_PAYLOAD_OFFSET + 8]),
                           "little", signed=True)
    if not 0 < p_off <= PAYLOAD_OFF_RANGE_LIMIT:
        raise AssertionError(
            f"{slot} payload_offset is {p_off}, which an earlier arm of "
            f"validate_manifest_header claims before the sum is ever formed; the "
            f"wrap arm needs an offset the ROM accepts"
        )
    value = PAYLOAD_LEN_RANGE_LIMIT
    wrapped = (p_off + value) & 0xFFFF_FFFF
    if wrapped >= p_off:
        raise AssertionError(
            f"{slot} (payload_offset {p_off} + payload_length {value}) & 0xFFFFFFFF "
            f"is {wrapped}, not below the offset, so `total < p_off` does not fire "
            f"and this is not the wrap stimulus"
        )
    if wrapped > SEP_SRAM_SIZE:
        raise AssertionError(
            f"{slot} wrapped sum {wrapped} exceeds the {SEP_SRAM_SIZE}-byte SEP "
            f"SRAM, so the capacity arm would also refuse the slot and the two "
            f"silent arms become indistinguishable"
        )
    was = declare_payload_length(buf, slot, value)
    return {
        "payload_offset": p_off,
        "payload_length_before": was,
        "payload_length": value,
        "wrapped_sum": wrapped,
        "sram_size": SEP_SRAM_SIZE,
        "len_range_limit": PAYLOAD_LEN_RANGE_LIMIT,
    }


def set_out_of_range_payload_offset(buf: bytearray, slot: str, value: int) -> int:
    """Declare a ``payload_offset`` wider than the 32 bits every consumer narrows it to.

    ``validate_manifest_header`` refuses ``payload_offset > +0x7FFFFFFF`` (and
    ``< -0x7FFFFFFF``) with ``MANIFEST_ERR_BAD_LENGTH``, announcing
    ``PAYLOAD_OFF_RANGE``, before the field is cast to ``int32_t``
    (``manifest_load.c``). Without that arm a value above 2 GiB would narrow to a
    small in-range offset and every later bound would be computed against it.

    THE VALUE IS WRITTEN ZERO-EXTENDED, which is the whole difficulty of this
    stimulus. ``payload_offset`` is ``int64_t``, so sign-extending a 32-bit
    boundary value such as ``0xFFFFFFFF`` stores ``-1``: that is inside the
    permitted negative range, narrows to ``-1``, and is then refused by the
    ``p_off <= 0`` arm -- same ``MANIFEST_ERR_BAD_LENGTH``, different arm, and no
    token at all. The stored value is read back as a signed 64-bit integer and
    required to exceed the positive limit, so that mistake fails here instead of
    passing as a generic length verdict.

    NO RE-SEAL. ``boot_arguments`` sits outside the TBS and outside the bytes
    ``manifest_hash`` covers (``manifest.h``), so the slot stays genuinely signed
    and the declared offset is the only thing wrong with it -- proved below
    against the real bytes rather than asserted in prose.

    THE PAYLOAD IS NOT MOVED: the refusal is the first payload decision the ROM
    makes, upstream of the fetch, so nothing at the declared offset is ever read.

    Returns the previous value.
    """
    base = mm.slot_base(slot)
    if not PAYLOAD_OFF_RANGE_LIMIT < value <= 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError(
            f"payload_offset {value} does not exceed the +0x{PAYLOAD_OFF_RANGE_LIMIT:x} "
            f"limit, so the PAYLOAD_OFF_RANGE arm is not the one that would claim it"
        )
    # Prove the slot is fully sealed BEFORE the write: the ROM refuses it upstream
    # of its own integrity check, so a broken seal would be invisible in the run.
    verify_sealed(buf, slot)
    verify_signing_key(buf, slot)
    was = int.from_bytes(bytes(buf[base + OFF_BOOT_PAYLOAD_OFFSET:
                                   base + OFF_BOOT_PAYLOAD_OFFSET + 8]),
                         "little", signed=True)

    _put_u64(buf, base + OFF_BOOT_PAYLOAD_OFFSET, value)

    stored = int.from_bytes(bytes(buf[base + OFF_BOOT_PAYLOAD_OFFSET:
                                      base + OFF_BOOT_PAYLOAD_OFFSET + 8]),
                            "little", signed=True)
    if stored <= PAYLOAD_OFF_RANGE_LIMIT:
        raise AssertionError(
            f"{slot} payload_offset reads {stored} as int64 after writing "
            f"0x{value:x}; it must exceed +0x{PAYLOAD_OFF_RANGE_LIMIT:x} or the "
            f"`p_off <= 0` arm claims the slot instead of PAYLOAD_OFF_RANGE. Write "
            f"the value zero-extended, not sign-extended"
        )
    # The claim that boot_arguments sits outside the signed and hashed regions is
    # what licenses not re-signing; assert it against the real bytes, so a future
    # move of the field fails loudly here instead of turning into a signature
    # rejection the run cannot tell apart from this one.
    mm.verify_layout(buf, slot)
    n, _e, _d = load_rsa_private_key()
    tbs = bytes(buf[base:base + mm.TBS_LEN])
    sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
    if not verify_pkcs1v15_sha256(tbs, sig, n):
        raise AssertionError(
            f"{slot} signature no longer verifies after writing payload_offset; the "
            f"field is supposed to sit outside the TBS, so either the offset moved "
            f"or the layout this mutator assumes is wrong"
        )
    return was
