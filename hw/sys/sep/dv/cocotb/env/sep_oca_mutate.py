# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Targeted mutation of a packed OCA boot manifest, for negative boot testcases.

Mutating the packed bytes here rather than in a build step keeps these testcases
Python-only: no new firmware profile and no HDL rebuild.

VARIANTS. The packer emits two: oca-classic (magic ``OCAC``) and oca-pqc
(``OCAP``, a 36864-byte body). Geometry is resolved from the magic via the
packer's own variant table, so :func:`slot_span` and :func:`slot_is_erased` work
for both. Field-level mutation is classic-only: ``constants.py`` does not publish
per-field PQC offsets yet ("added with the validator's PQC support"), and
computing them here from the trailer shift would be the hardcoding this module
exists to avoid. PQC field access raises.

LAYOUT AND THE SIGNED BOUNDARY. An OCA-classic body is 4096 bytes::

    [0    .. 3171]  signed region, covered by manifest_hash and the signature
    [3172 .. 3683]  signature_classic (512 B field; signature_size_classic says
                    how many bytes are valid, 384 for RSA-3072)
    [3684 .. 3747]  manifest_hash (64 B field; SHA-256 in the low 32, rest 0x00)

That boundary decides what a mutation costs, and :func:`verify_layout` checks it
against the shipped image rather than trusting it:

  * A field OUTSIDE the signed region is written directly.
  * A field INSIDE it invalidates ``manifest_hash``, so :func:`rehash` must
    follow. Re-signing is separate: the ROM checks structure and the hash before
    it checks the signature, so a mutation meant to be rejected before the RSA
    step needs no key. One that must survive PAST signature verification does.

THIS DIFFERS FROM GRENDEL IN A WAY TESTS FEEL. Grendel's ``flag_args`` -- BL2
demotion and the secure-boot flag -- sat outside the hashed region, so those bits
could be flipped for free and still boot. OCA's ``demotion_control`` (offset 172)
and ``secure_boot_control`` (182) are inside the signed region. A test that needs
a manifest which *requests* a policy should get it from the pack config, not by
mutation; mutation is for values that must be refused.

LAYOUT COMES FROM THE PACKER, NOT FROM HERE. Offsets are loaded from the
tt-oca-manifest submodule's ``src/oca/constants.py`` and the manifest_hash field
is built by its ``manifest.compute_manifest_hash``, so the packer stays the one
authority for both the offsets and the field's shape. The three modules are
loaded by path under a bare ``oca`` package rather than imported normally,
because the real ``__init__`` reaches ``entry`` -> ``encryption`` ->
``cryptography``, which the DV virtualenv does not have; ``constants``,
``validators`` and ``manifest`` themselves need only the stdlib. A failure to
load is raised, never defaulted: a literal fallback would drift silently the
first time the format moved.

Run ``python3 sep_oca_mutate.py`` to check the layout assumptions against every
packed image in ``bootrom/prod/build``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from pathlib import Path

_SEP_ROOT = Path(__file__).resolve().parents[3]
_OCA_SRC = _SEP_ROOT / "bootrom" / "prod" / "tools" / "tt-oca-manifest" / "src" / "oca"

# constants must precede validators, which manifest imports.
_OCA_MODULES = ("constants", "validators", "manifest")


def _load_oca():
    """Load the packer's stdlib-only modules under a bare ``oca`` package.

    The real ``oca/__init__.py`` imports ``entry``, which reaches ``encryption``
    and therefore ``cryptography`` -- absent from the DV virtualenv. Registering
    an empty package under the same name lets the submodules' relative imports
    resolve without it. The name has to be ``oca`` for those imports to work, and
    nothing else provides it, but an already-imported real package is reused
    rather than shadowed.
    """
    missing = [n for n in _OCA_MODULES if not (_OCA_SRC / f"{n}.py").is_file()]
    if missing:
        raise ImportError(
            f"{_OCA_SRC} is missing {', '.join(missing)}. The packer is the "
            f"authority for OCA manifest layout, and hardcoding it here would "
            f"drift the first time the format moved. Check out the "
            f"tt-oca-manifest submodule under bootrom/prod/tools/."
        )
    if "oca" not in sys.modules:
        pkg = types.ModuleType("oca")
        pkg.__path__ = [str(_OCA_SRC)]
        sys.modules["oca"] = pkg
    loaded = {}
    for name in _OCA_MODULES:
        full = f"oca.{name}"
        if full in sys.modules:
            loaded[name] = sys.modules[full]
            continue
        spec = importlib.util.spec_from_file_location(full, _OCA_SRC / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
        loaded[name] = module
    return loaded["constants"], loaded["manifest"]


K, MF = _load_oca()

# Slot offsets in the packed image, matching the ROM's compiled-in
# PRIMARY_MANIFEST_OFFSET / BACKUP_MANIFEST_OFFSET. Unchanged from the Grendel
# packer, and asserted against the shipped image by verify_layout().
PRIMARY_MANIFEST_OFFSET = 0x1000
BACKUP_MANIFEST_OFFSET = 0x41000

MANIFEST_MAGIC = K.OCAC_MAGIC
BODY_SIZE = K.OCA_CLASSIC_BODY_SIZE
SIGNED_REGION_END = K.OCA_CLASSIC_SIGNED_REGION_END

_VARIANTS = (K.CLASSIC_VARIANT, K.PQC_VARIANT)


def variant_at(buf: bytes, base: int):
    """The packer's variant descriptor for the manifest at ``base``, by magic."""
    magic = bytes(buf[base : base + 4])
    for v in _VARIANTS:
        if magic == v.magic:
            return v
    raise AssertionError(
        f"manifest at 0x{base:x} carries magic {magic!r}, which is neither "
        f"{K.OCAC_MAGIC!r} nor {K.OCAP_MAGIC!r}; the image is not a packed OCA "
        f"manifest"
    )


def require_classic(buf: bytes, slot: str):
    """Variant descriptor for ``slot``, refusing PQC.

    Field-level mutators call this. PQC bodies have a different field layout and
    the packer does not publish those offsets yet, so a mutator that assumed the
    classic ones would write into the wrong bytes and still look like it worked.
    """
    v = variant_at(buf, slot_base(slot))
    if v.magic != K.OCAC_MAGIC:
        raise AssertionError(
            f"{slot} manifest is {v.format_name}; field-level mutation is "
            f"classic-only because constants.py does not publish per-field PQC "
            f"offsets yet. Geometry (slot_span, erase_slot) works for both."
        )
    return v


OFF_MANIFEST_HASH = K.OFF_MANIFEST_HASH
OFF_SIGNATURE = K.OFF_SIGNATURE_CLASSIC
OFF_SIGNATURE_TYPE = K.OFF_SIGNATURE_TYPE_CLASSIC
OFF_SIGNATURE_SIZE = K.OFF_SIGNATURE_SIZE_CLASSIC

# A digest field is HASH_FIELD_SIZE wide with the SHA-256 in the low DIGEST_LEN
# bytes and the rest 0x00.
DIGEST_LEN = 32
HASH_FIELD_SIZE = K.HASH_FIELD_SIZE

# Erased-flash byte. Matches the BFM's backing store and its out-of-range read
# value (ocah_spi_flash.py), so an erased region and an address past the end of
# the image are indistinguishable to the ROM -- which is what makes 0xFF the
# honest representation of "nothing is programmed here".
ERASED_BYTE = 0xFF


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
    offset -- so the span, not just the 4096-byte body, is what "this address
    holds a bootable slot" means.

    ``image`` may be the buffer or just its length, so a caller that knows only
    the size need not fabricate a quarter-megabyte throwaway buffer.
    """
    start = slot_base(slot)
    image_len = image if isinstance(image, int) else len(image)
    end = BACKUP_MANIFEST_OFFSET if slot == "primary" else image_len
    # A span is geometry, so this must answer for an ERASED slot too -- erase_slot
    # and slot_is_erased both need it after the magic is gone. Use the variant's
    # body size when a magic is there to name one, else the smallest known body
    # as the floor.
    body = BODY_SIZE
    if not isinstance(image, int):
        try:
            body = variant_at(image, start).body_size
        except AssertionError:
            body = min(v.body_size for v in _VARIANTS)
    if end < start + body:
        raise AssertionError(
            f"image is too small to contain the {slot} slot: span "
            f"0x{start:x}..0x{end:x} is under {body} bytes. Either the image is "
            f"truncated or the slot offsets no longer match the packer"
        )
    return start, end


def manifest_hash_field(buf: bytes, base: int) -> bytes:
    """The manifest_hash field the packer would write for this body.

    Delegates to the packer so the digest and the field's zero padding come from
    the same code that produced the shipped images.
    """
    v = variant_at(buf, base)
    return MF.compute_manifest_hash(bytes(buf[base : base + v.signed_region_end]), v)


def verify_layout(buf: bytes, slot: str) -> None:
    """Assert the packed image matches the layout this module assumes.

    Called by every mutation entry point. Without it, a packer change (a moved
    field, a different signed boundary) would turn every mutation into a write
    into the wrong bytes -- and because these are negative tests, the ROM would
    still reject the image and the test would still look like it passed for the
    stated reason. This converts that silent-wrong-reason failure into a loud one.
    """
    base = slot_base(slot)
    v = require_classic(buf, slot)
    stored = bytes(buf[base + OFF_MANIFEST_HASH : base + OFF_MANIFEST_HASH + HASH_FIELD_SIZE])
    calc = manifest_hash_field(buf, base)
    if stored != calc:
        raise AssertionError(
            f"{slot} manifest_hash does not equal "
            f"sha256(body[0:{v.signed_region_end}]) (stored {stored.hex()}, computed "
            f"{calc.hex()}); the signed boundary or the hash offset in "
            f"sep_oca_mutate no longer matches the packer"
        )


def rehash(buf: bytearray, slot: str) -> None:
    """Recompute ``manifest_hash`` after a mutation inside the signed region.

    Writes the whole field, padding included, so a stale tail cannot survive a
    rehash.
    """
    require_classic(buf, slot)
    base = slot_base(slot)
    buf[base + OFF_MANIFEST_HASH : base + OFF_MANIFEST_HASH + HASH_FIELD_SIZE] = (
        manifest_hash_field(buf, base)
    )


def erase_slot(buf: bytearray, slot: str) -> tuple[int, int]:
    """Fill a slot's whole flash span with 0xFF, i.e. make the address read blank.

    The "address not detected" stimulus: the ROM has no SPI device probe, so its
    only presence test is the manifest magic, and an erased slot is therefore
    indistinguishable from an absent device.

    The layout is verified BEFORE erasing, which is the point: it proves a valid
    manifest really was at this address, so the test is removing a working slot
    rather than erasing empty space and asserting on a no-op.
    """
    variant_at(buf, slot_base(slot))  # a valid manifest really is here
    start, end = slot_span(buf, slot)
    buf[start:end] = bytes([ERASED_BYTE]) * (end - start)
    return start, end


def slot_is_erased(buf: bytes, slot: str) -> bool:
    """True iff every byte of the slot's span reads as the erased value."""
    start, end = slot_span(buf, slot)
    return all(b == ERASED_BYTE for b in bytes(buf[start:end]))


def signature_type(buf: bytes, slot: str) -> int:
    """``signature_type_classic``: 1 = RSA-3072, 5 = ECDSA-P256, 0 = unsigned."""
    require_classic(buf, slot)
    return buf[slot_base(slot) + OFF_SIGNATURE_TYPE]


def signature_size(buf: bytes, slot: str) -> int:
    """Valid byte count within the 512-byte signature field."""
    require_classic(buf, slot)
    base = slot_base(slot) + OFF_SIGNATURE_SIZE
    return int.from_bytes(bytes(buf[base : base + 2]), "little")


def describe(buf: bytes, slot: str) -> str:
    """One-line summary of a slot, for test log lines. Works for either variant."""
    base = slot_base(slot)
    v = variant_at(buf, base)
    out = f"{slot}@0x{base:x} {v.format_name} body={v.body_size}"
    if v.magic == K.OCAC_MAGIC:
        digest = bytes(buf[base + OFF_MANIFEST_HASH : base + OFF_MANIFEST_HASH + 8])
        out += (
            f" sig_type={signature_type(buf, slot)}"
            f" sig_size={signature_size(buf, slot)} hash={digest.hex()}..."
        )
    return out


# ---------------------------------------------------------------------------
# Public key selection and the key itself
# ---------------------------------------------------------------------------
# public_key_select_classic is a 128-bit bitmap with exactly one bit set; the
# validator refuses two with PUBK_SEL_AMBIGUOUS rather than picking one. The bit
# numbering is CHIPLET_PUBK_REVOKE's own, so authorize-slot-N and revoke-slot-N
# name the same key (oca_platform.c).
OFF_PUBLIC_KEY_SEL = K.OFF_PUBLIC_KEY_SELECT_CLASSIC
OFF_PUBLIC_KEY = K.OFF_PUBLIC_KEY_CLASSIC
PUBLIC_KEY_SEL_LEN = 16
MODULUS_LEN = K.RSA_3072_MODULUS_BYTES

# Selection kinds, keeping the names the Grendel API used, mapped onto slots.
PUBK_SEL_ROM_KEY = 0
PUBK_SEL_FUSE_KEY_0 = 1
PUBK_SEL_FUSE_KEY_1 = 2

# Slots 0..7 are ROM classical keys; key_digests.c provisions six, so 6 is the
# smallest index the ROM key table must reject.
PUBK_SEL_NUM_ROM_KEYS = 6
KEY_SLOT_CHIPLET_PUBK_HASH0 = 16
KEY_SLOT_CHIPLET_PUBK_HASH1 = 17

OFF_PUBLIC_KEY_ENCODING = K.OFF_PUBLIC_KEY_ENCODING_CLASSIC
SIG_TYPE_RSA_3072 = K.OcaClassicSignatureType.RSA_3072_PKCS1V15_SHA256.value
SIG_TYPE_ECDSA_P256 = K.OcaClassicSignatureType.ECDSA_P256_SHA256.value
SIG_TYPE_NO_SIGNATURE = 0
ENCODING_RAW = K.OcaClassicSignatureEncoding.RAW_BYTES.value

_KEY_DIGESTS_C = _SEP_ROOT / "bootrom" / "prod" / "src" / "key_digests.c"


def key_slot_for(selection: int, index: int = 0) -> int:
    """Bitmap slot number a (selection, index) pair names."""
    if selection == PUBK_SEL_ROM_KEY:
        return index
    if selection in (PUBK_SEL_FUSE_KEY_0, PUBK_SEL_FUSE_KEY_1):
        return KEY_SLOT_CHIPLET_PUBK_HASH0 + (selection - PUBK_SEL_FUSE_KEY_0)
    raise ValueError(f"unknown selection {selection}")


def set_public_key_sel(buf: bytearray, slot: str, *, selection: int, index: int = 0) -> int:
    """Set the bitmap to name exactly one key slot. Returns that slot number.

    Clears the field first: more than one bit set is ambiguous and the validator
    refuses it, so a mutator that only OR-ed a bit in would be testing the
    ambiguity refusal rather than the selection it meant to plant.
    """
    require_classic(buf, slot)
    bit = key_slot_for(selection, index)
    if not 0 <= bit < 8 * PUBLIC_KEY_SEL_LEN:
        raise ValueError(f"slot {bit} is outside the {8 * PUBLIC_KEY_SEL_LEN}-bit bitmap")
    base = slot_base(slot) + OFF_PUBLIC_KEY_SEL
    field = bytearray(PUBLIC_KEY_SEL_LEN)
    field[bit // 8] = 1 << (bit % 8)
    buf[base : base + PUBLIC_KEY_SEL_LEN] = field
    rehash(buf, slot)
    return bit


def get_public_key_sel(buf: bytes, slot: str) -> int:
    """The one key slot the bitmap names.

    Returns the slot number, not the raw field: under OCA the slot number is what
    both the authorization callback and the revocation bitmap index with, so it is
    the value a test wants to assert on. Raises if the bitmap names none or more
    than one, because both are refusals rather than selections.
    """
    require_classic(buf, slot)
    base = slot_base(slot) + OFF_PUBLIC_KEY_SEL
    field = bytes(buf[base : base + PUBLIC_KEY_SEL_LEN])
    bits = [b for b in range(8 * PUBLIC_KEY_SEL_LEN) if (field[b // 8] >> (b % 8)) & 1]
    if len(bits) != 1:
        raise AssertionError(
            f"{slot} public_key_select names {len(bits)} slots ({bits}); the "
            f"validator refuses anything but exactly one. Field: {field.hex()}"
        )
    return bits[0]


def public_key_modulus(buf: bytes, slot: str) -> bytes:
    """The 384-byte big-endian RSA-3072 modulus, which the digests cover.

    A raw RSA public key is the modulus followed by a 4-byte exponent; only the
    modulus is hashed, so the exponent is deliberately excluded here.
    """
    require_classic(buf, slot)
    base = slot_base(slot) + OFF_PUBLIC_KEY
    return bytes(buf[base : base + MODULUS_LEN])


def rom_key_digest(index: int) -> bytes:
    """Provisioned SHA-256 for a ROM key slot, read from generated key_digests.c.

    Parsed rather than copied: the file is generated by generate_key_digests.py
    and its values change when the keys do, so a literal here would go stale
    silently and take every key test with it.
    """
    import re

    if not _KEY_DIGESTS_C.is_file():
        raise AssertionError(f"{_KEY_DIGESTS_C} not found; it holds the provisioned digests")
    text = _KEY_DIGESTS_C.read_text()
    m = re.search(rf"digest_rom_key{index}\[[^\]]*\]\s*=\s*{{(.*?)}}", text, re.S)
    if m is None:
        raise AssertionError(f"key_digests.c has no digest_rom_key{index}")
    digest = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]{2})", m.group(1)))
    if len(digest) != DIGEST_LEN:
        raise AssertionError(f"digest_rom_key{index} is {len(digest)} bytes, expected {DIGEST_LEN}")
    return digest


def public_key_encoding(buf: bytes, slot: str) -> int:
    """``public_key_encoding_classic``: 1 = ASN.1 DER, 2 = raw bytes."""
    require_classic(buf, slot)
    return buf[slot_base(slot) + OFF_PUBLIC_KEY_ENCODING]


def can_anchor_public_key(buf: bytes, slot: str) -> bool:
    """True when this slot's key can be checked against a digest in the tree.

    Three things have to hold, the same three plat_is_key_authorized() requires
    before it compares a digest: the anchor is a ROM slot (an OTP slot's digest
    is in a fuse bank, not the source tree), the algorithm is RSA-3072 (the
    digests cover a 384-byte modulus), and the encoding is raw (a DER key wraps
    the modulus in ASN.1, so it is not at the field start).
    """
    return (
        get_public_key_sel(buf, slot) < PUBK_SEL_NUM_ROM_KEYS
        and signature_type(buf, slot) == SIG_TYPE_RSA_3072
        and public_key_encoding(buf, slot) == ENCODING_RAW
    )


def verify_public_key(buf: bytes, slot: str) -> int:
    """Assert the slot's modulus is the key its selection claims. Returns the slot.

    Anchors OFF_PUBLIC_KEY against real bytes: if the offset were wrong the digest
    would not match, so this doubles as the layout check for the key field. When
    the key cannot be anchored from the tree (see can_anchor_public_key) the slot
    is returned unchecked.
    """
    key_slot = get_public_key_sel(buf, slot)
    if not can_anchor_public_key(buf, slot):
        return key_slot
    want = rom_key_digest(key_slot)
    got = hashlib.sha256(public_key_modulus(buf, slot)).digest()
    if got != want:
        raise AssertionError(
            f"{slot} modulus does not hash to the provisioned digest for ROM key "
            f"{key_slot}: sha256(modulus)={got.hex()}, key_digests.c={want.hex()}. "
            f"Either OFF_PUBLIC_KEY is wrong or the image is signed by another key"
        )
    return key_slot


def corrupt_public_key(buf: bytearray, slot: str, *, offset: int = 0) -> int:
    """Flip one bit of the modulus so its digest no longer matches. Returns offset.

    The digest check is the target, so the mutation stays inside the modulus: the
    exponent is outside what the digest covers and flipping it would prove
    nothing about key anchoring.
    """
    if not can_anchor_public_key(buf, slot):
        raise AssertionError(
            f"{slot} key cannot be anchored from the tree, so corrupting its "
            f"modulus proves nothing: slot={get_public_key_sel(buf, slot)}, "
            f"sig_type={signature_type(buf, slot)}, "
            f"encoding={public_key_encoding(buf, slot)}"
        )
    verify_public_key(buf, slot)
    if not 0 <= offset < MODULUS_LEN:
        raise ValueError(f"offset {offset} is outside the {MODULUS_LEN}-byte modulus")
    at = slot_base(slot) + OFF_PUBLIC_KEY + offset
    buf[at] ^= 0xFF
    rehash(buf, slot)
    return offset


def flip_signature_byte(buf: bytearray, slot: str, *, offset: int = 0) -> int:
    """Flip one signature byte. Returns the offset flipped.

    No rehash: the signature is outside the signed region, so the manifest hash
    still matches and the run reaches signature verification -- which is the
    point, since a hash mismatch would reject the image earlier and prove nothing
    about the verifier.
    """
    require_classic(buf, slot)
    span = OFF_MANIFEST_HASH - OFF_SIGNATURE
    if not 0 <= offset < span:
        raise ValueError(f"offset {offset} is outside the {span}-byte signature field")
    buf[slot_base(slot) + OFF_SIGNATURE + offset] ^= 0xFF
    return offset


def _selftest() -> int:
    """Check the layout assumptions against every packed image on disk."""
    build = _SEP_ROOT / "bootrom" / "prod" / "build"
    images = sorted(build.glob("oca_*_boot.bin"))
    if not images:
        print(f"no packed images in {build}; run `make oca-images` first")
        return 1
    print(f"layout from {_OCA_SRC} ({', '.join(_OCA_MODULES)})")
    print(f"  magic={MANIFEST_MAGIC!r} body={BODY_SIZE} signed=[0,{SIGNED_REGION_END})")
    print(f"  hash@{OFF_MANIFEST_HASH} sig@{OFF_SIGNATURE}\n")
    bad = classic = pqc = 0
    for img in images:
        buf = img.read_bytes()
        try:
            v = variant_at(buf, slot_base("primary"))
            # Geometry holds for both variants.
            for slot in ("primary", "backup"):
                slot_span(buf, slot)
                variant_at(buf, slot_base(slot))
            if v.magic != K.OCAC_MAGIC:
                # Field-level checks do not apply; assert that they refuse
                # rather than silently reading classic offsets.
                pqc += 1
                try:
                    verify_layout(buf, "primary")
                except AssertionError:
                    print(f"  ok   {describe(buf, 'primary')} (fields correctly refused)")
                else:
                    print(f"  FAIL {img.name}: PQC body accepted by a classic-only check")
                    bad += 1
                continue

            verify_layout(buf, "primary")
            verify_layout(buf, "backup")
            # rehash is a no-op on an unmutated image, and restores the stored
            # digest after a mutation inside the signed region.
            m = bytearray(buf)
            rehash(m, "primary")
            if bytes(m) != buf:
                print(f"  FAIL {img.name}: rehash changed an unmutated image")
                bad += 1
            m[slot_base("primary") + 64] ^= 0xFF
            try:
                verify_layout(m, "primary")
            except AssertionError:
                pass
            else:
                print(f"  FAIL {img.name}: a mutated signed region still verified")
                bad += 1
            rehash(m, "primary")
            verify_layout(m, "primary")
            # Erasure is geometry-only and must leave the slot reading blank.
            e = bytearray(buf)
            erase_slot(e, "backup")
            if not slot_is_erased(e, "backup"):
                print(f"  FAIL {img.name}: erase_slot left non-0xFF bytes")
                bad += 1
            # Key selection and anchoring, on the signed images only: the
            # unsigned one carries no key to check.
            if signature_type(buf, "primary") != SIG_TYPE_NO_SIGNATURE:
                key_slot = verify_public_key(buf, "primary")
                anchorable = can_anchor_public_key(buf, "primary")
                m = bytearray(buf)
                # A round trip through the bitmap must name the slot it was given.
                for sel, idx in ((PUBK_SEL_ROM_KEY, 3), (PUBK_SEL_FUSE_KEY_0, 0)):
                    want = set_public_key_sel(m, "primary", selection=sel, index=idx)
                    if get_public_key_sel(m, "primary") != want:
                        print(f"  FAIL {img.name}: key-sel round trip lost slot {want}")
                        bad += 1
                # Corrupting the modulus must break the anchor, and the
                # signature flip must NOT disturb the manifest hash.
                if anchorable:
                    m = bytearray(buf)
                    corrupt_public_key(m, "primary")
                    try:
                        verify_public_key(m, "primary")
                    except AssertionError:
                        pass
                    else:
                        print(f"  FAIL {img.name}: corrupted modulus still anchored")
                        bad += 1
                m = bytearray(buf)
                flip_signature_byte(m, "primary")
                verify_layout(m, "primary")
                if bytes(m) == bytes(buf):
                    print(f"  FAIL {img.name}: flip_signature_byte changed nothing")
                    bad += 1
                classic += 1
                tag = f"key_slot{key_slot}" + ("" if anchorable else " (not anchorable)")
                print(f"  ok   {describe(buf, 'primary')} {tag}")
                continue

            classic += 1
            print(f"  ok   {describe(buf, 'primary')}")
        except AssertionError as exc:
            print(f"  FAIL {img.name}: {exc}")
            bad += 1
    print(f"\n{len(images)} image(s): {classic} classic, {pqc} pqc, {bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
