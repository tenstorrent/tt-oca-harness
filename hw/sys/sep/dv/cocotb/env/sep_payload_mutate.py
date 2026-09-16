# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Payload/TOC mutation for boot testcases whose defect lives PAST the crypto chain.

WHY THIS IS A SEPARATE MODULE FROM ``sep_manifest_mutate``. Every mutation that
module performs is rejected before the RSA step, so the stale signature is never
reached and it does not re-sign. The defects here are the opposite case. BL1 size, BL1
entry point and post-decrypt TOC content are all validated by
``validate_manifest_payload()`` / ``check_bl1_image()``, which run AFTER
``manifest_crypto_validate()`` has verified the signature
(``manifest_load.c``). A payload mutation that is not
re-sealed therefore never reaches the check it is aimed at: it dies at
``PLD_HASH_MISMATCH`` (``manifest_crypto.c``), or at ``SIG_FAILED`` once
``payload_hash`` -- which sits INSIDE the TBS at offset 552 -- is corrected.

So these mutations must re-seal the slot, in this order:

    per-image hash  ->  payload_hash  ->  manifest_hash  ->  RSA signature

RE-SIGNING. The images under test are signed with the dev0 test key, whose private
half is in the ``tt-boot-manifest`` submodule at
``bootrom/prod/tools/tt-boot-manifest/tests/signing_keys/rsa_private_key.dev0.pem``
and whose modulus digest is the ROM's own key slot 0
(``bootrom/prod/src/key_digests.c:19-21``). Re-signing keeps the ROM's signature
check enabled and satisfied by a correctly signed image, so the BL1 verdict is
reached by the same crypto path production uses.

SIGNING USES ONLY THE STANDARD LIBRARY. :func:`sign_pkcs1v15_sha256` implements
EMSA-PKCS1-v1_5 directly (the packer's scheme: ``manifest_signing.py``,
``PKCS1v15()`` + ``SHA256``), so no third-party crypto module is required.
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
OFF_PAYLOAD_HASH = 552  # 32 B, SHA-256 over payload[:payload_hashed_length]
OFF_PAYLOAD_HASHED_LEN = 584  # uint64
OFF_PAYLOAD_LENGTH = 600  # uint64
OFF_BOOT_PAYLOAD_OFFSET = 1160  # int64, first field of boot_arguments
OFF_USAGE_FLAGS = 92  # uint32, usage_constraints.flags (16 + 76)

# ── TOC layout (manifest.h) ──────────────────────────────────────────
TOC_MAGIC = b"PTOC"  # TOC_HEADER_MAGIC_WORD 0x434f5450
TOC_HDR_SIZE = 32
TOC_ENTRY_SIZE = 216
TOC_OFF_PAYLOAD_LENGTH = 8  # uint64 in the header
TOC_OFF_IMAGE_COUNT = 16  # uint64 in the header

# Field offsets within a toc_entry.
E_TYPE = 0
E_OFFSET = 8
E_LENGTH = 16
E_LOAD_ADDR = 32
E_ENTRY_POINT = 40
E_HASH = 56

# IMAGE_TYPE_SEP_BL1, manifest.h -- "SEPBL1" packed little-endian into a u64.
IMAGE_TYPE_SEP_BL1 = 0x0000_314C_4250_4553

# check_bl1_image()'s load window, manifest.h.
SEP_SRAM_BASE = 0x1000_0000
SEP_SRAM_SIZE = 0x0004_0000

# manifest.h -- both check_bl1_image() arms return this one error code.
MANIFEST_ERR_BL1_BAD_ADDR = 0x0003_000A
# manifest.h
MANIFEST_ERR_BAD_TOC_ID = 0x0003_0005

# The dev0 signing key, relative to the repo's sep root.
_SEP_ROOT = Path(__file__).resolve().parents[3]
DEV0_KEY = (
    _SEP_ROOT
    / "bootrom"
    / "prod"
    / "tools"
    / "tt-boot-manifest"
    / "tests"
    / "signing_keys"
    / "rsa_private_key.dev0.pem"
)

# EMSA-PKCS1-v1_5 DigestInfo prefix for SHA-256 (RFC 8017 section 9.2, note 1).
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")

RSA_KEY_BYTES = 384  # RSA-3072


# ── minimal DER / PKCS#8 reader ───────────────────────────────────────────────
def _der_len(b: bytes, i: int) -> tuple[int, int]:
    n = b[i]
    i += 1
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(b[i : i + k], "big")
        i += k
    return n, i


def _der_tlv(b: bytes, i: int) -> tuple[int, bytes, int]:
    tag = b[i]
    i += 1
    ln, i = _der_len(b, i)
    return tag, b[i : i + ln], i + ln


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
    _, _, i = _der_tlv(info, i)  # version
    _, _, i = _der_tlv(info, i)  # algorithm identifier
    tag, pk, _ = _der_tlv(info, i)  # privateKey OCTET STRING
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
    return int.from_bytes(bytes(buf[at : at + 8]), "little")


def _put_u64(buf: bytearray, at: int, value: int) -> None:
    buf[at : at + 8] = int(value).to_bytes(8, "little")


def payload_base(buf, slot: str) -> int:
    """Flash byte offset of ``slot``'s payload (manifest base + payload_offset)."""
    base = mm.slot_base(slot)
    off = int.from_bytes(
        bytes(buf[base + OFF_BOOT_PAYLOAD_OFFSET : base + OFF_BOOT_PAYLOAD_OFFSET + 8]),
        "little",
        signed=True,
    )
    return base + off


def manifest_payload_length(buf, slot: str) -> int:
    return _u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_LENGTH)


def payload_hashed_length(buf, slot: str) -> int:
    return _u64(buf, mm.slot_base(slot) + OFF_PAYLOAD_HASHED_LEN)


def is_encrypted(buf, slot: str) -> bool:
    """usage_constraints.flags bit 1, manifest.h."""
    base = mm.slot_base(slot)
    flags = int.from_bytes(
        bytes(buf[base + OFF_USAGE_FLAGS : base + OFF_USAGE_FLAGS + 4]), "little"
    )
    return bool((flags >> 1) & 1)


def read_bytes(buf, start: int, length: int) -> bytes:
    """Flash bytes as the ROM will see them, padding past the image with 0xFF.

    The SPI BFM's backing store and its out-of-range reads are both 0xFF
    (``ocah_spi_flash.py``), so a read that runs past the programmed
    image returns erased bytes rather than failing. Modelling that here is what
    lets a testcase declare an image size larger than the material actually
    programmed and still know, exactly, which bytes the ROM will hash.
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
    return (
        f"{slot} BL1: offset={_u64(buf, e + E_OFFSET)} "
        f"length={_u64(buf, e + E_LENGTH)} "
        f"load_addr=0x{_u64(buf, e + E_LOAD_ADDR):08x} "
        f"entry_point=0x{_u64(buf, e + E_ENTRY_POINT):x} "
        f"payload_length={manifest_payload_length(buf, slot)}"
    )


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
    stored = bytes(buf[base + OFF_PAYLOAD_HASH : base + OFF_PAYLOAD_HASH + 32])
    calc = hashlib.sha256(read_bytes(buf, p, hashed)).digest()
    if stored != calc:
        raise AssertionError(
            f"{slot} payload_hash does not equal sha256(payload[:{hashed}]) "
            f"(stored {stored.hex()}, computed {calc.hex()}); either the slot is not "
            f"sealed or OFF_PAYLOAD_HASH/OFF_PAYLOAD_HASHED_LEN are wrong"
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
                f"({p_len}); validate_manifest_payload rejects this as TOC_PLEN_MISMATCH"
            )
        for i, e in enumerate(toc_entries(buf, slot)):
            off, ln = _u64(buf, e + E_OFFSET), _u64(buf, e + E_LENGTH)
            want = bytes(buf[e + E_HASH : e + E_HASH + 32])
            got = hashlib.sha256(read_bytes(buf, p + off, ln)).digest()
            if want != got:
                raise AssertionError(
                    f"{slot} image {i} digest mismatch (stored {want.hex()}, "
                    f"computed {got.hex()} over payload[{off}:{off + ln}]); the ROM "
                    f"would reject this as IMAGE_HASH_MISMATCH, not the planted defect"
                )

    n, e_pub, _d = load_rsa_private_key()
    tbs = bytes(buf[base : base + mm.TBS_LEN])
    sig = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
    if not verify_pkcs1v15_sha256(tbs, sig, n):
        raise AssertionError(
            f"{slot} signature does not verify against the dev0 modulus; the ROM "
            f"would reject this slot as SIG_FAILED before reaching the payload checks"
        )


def verify_signing_key(buf, slot: str) -> None:
    """Prove the local signer reproduces the packer's signature, byte for byte.

    This is the load-bearing check for every re-sealed image. If
    :func:`sign_pkcs1v15_sha256` regenerates the SHIPPED signature of an untouched
    slot exactly, then the padding, the digest prefix, the TBS boundary and the key
    parse are all correct, and a signature it produces over modified bytes is a
    genuine dev0 signature. Without this the re-seal would be an unverified claim,
    and its failure mode -- the ROM rejecting the slot as SIG_FAILED -- looks like a
    plausible negative-test result.
    """
    base = mm.slot_base(slot)
    n, _e, d = load_rsa_private_key()
    tbs = bytes(buf[base : base + mm.TBS_LEN])
    shipped = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + RSA_KEY_BYTES])
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
    buf[entry + E_HASH : entry + E_HASH + 32] = hashlib.sha256(
        read_bytes(buf, p + off, ln)
    ).digest()


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
    buf[base + OFF_PAYLOAD_HASH : base + OFF_PAYLOAD_HASH + 32] = hashlib.sha256(
        read_bytes(buf, p, hashed)
    ).digest()
    mm.rehash(buf, slot)  # manifest_hash = sha256(TBS)
    n, _e, d = load_rsa_private_key()
    tbs = bytes(buf[base : base + mm.TBS_LEN])
    buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + RSA_KEY_BYTES] = sign_pkcs1v15_sha256(
        tbs, n, d
    )


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
    """Give BL1 a zero image size -- the "zero" size class of TP053-S.

    SIZE CLASS. The procedure names three (zero, larger than IRAM, larger than the
    spec's max BL1 size); only the first is reachable without growing the payload
    past 256 KiB on both slots. The reason is check ordering inside
    ``validate_manifest_payload``:

      * ``manifest_load.c`` rejects ``offset + length > payload_length`` as
        ``MANIFEST_ERR_IMAGE_OOB`` before anything BL1-specific runs, so an
        oversized length can only be reached by GROWING the payload to match.
      * ``check_bl1_image``'s containment arm (``manifest.h``,
        ``BL1_ADDR_RANGE``) only fires once ``load_addr + length`` leaves the
        256 KiB ICCM window. With the shipped ``load_addr`` of 0xC0000000 that
        needs length > 0x40000, i.e. a >256 KiB payload fetched over SPI on both
        slots.
      * The explicit ``length == 0 || length > SEP_SRAM_SIZE`` gate at
        ``rom_handoff.c`` (``BL1_SIZE`` / ``MANIFEST_ERR_BL1_TOO_LARGE``)
        is downstream of manifest validation, and ``manifest_load.c``
        says so in as many words: by the time handoff runs the slot has already
        been accepted. Both of its arms are therefore already rejected upstream.

    So zero is the class this ROM demonstrates unambiguously, at
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


def corrupt_ciphertext(
    buf: bytearray, slot: str, *, block: int = 0, byte_index: int = 0, mask: int = 0x01
) -> tuple[int, int]:
    """Flip a bit of the ENCRYPTED payload so the plaintext TOC magic cannot survive.

    TP049 variant (b). AES-CBC decryption never reports an error for wrong input --
    it is a permutation, so any ciphertext decrypts to something -- and the ROM's
    own ``aes128cbc_decrypt`` only fails on a bad length or an engine alert
    (``aes_driver.c``). The failure therefore has to surface
    DOWNSTREAM, at the TOC identifier check (``manifest_load.c``), which is
    exactly what the procedure asks for: "corrupt the encrypted payload so the
    decrypted plaintext does not match the TOC magic".

    Block 0 is the target: in CBC, ``P0 = D(C0) XOR IV``, so altering
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
