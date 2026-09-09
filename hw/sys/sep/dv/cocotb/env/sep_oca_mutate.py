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

OFFSETS COME FROM THE PACKER, NOT FROM HERE. Every constant is loaded from the
tt-oca-manifest submodule's ``src/oca/constants.py``, which is the authority for
manifest layout. It is loaded by file path rather than imported as ``oca.constants``
because the package's ``__init__`` pulls in the packer's crypto dependencies and
the DV virtualenv has none; ``constants.py`` itself needs only the stdlib. A
failure to load is raised, never defaulted: a literal fallback would drift
silently the first time the format moved.

Run ``python3 sep_oca_mutate.py`` to check the layout assumptions against every
packed image in ``bootrom/prod/build``.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

_SEP_ROOT = Path(__file__).resolve().parents[3]
_OCA_CONSTANTS = (
    _SEP_ROOT / "bootrom" / "prod" / "tools" / "tt-oca-manifest" / "src" / "oca" / "constants.py"
)


def _load_oca_constants():
    """Load the packer's constants module from its file, without its package.

    Importing ``oca.constants`` would run ``oca/__init__.py``, which reaches
    ``oca.encryption`` and therefore ``cryptography`` -- absent from the DV
    virtualenv. ``constants.py`` imports only the stdlib, so it loads alone.
    """
    if not _OCA_CONSTANTS.is_file():
        raise ImportError(
            f"{_OCA_CONSTANTS} not found. It is the authority for OCA manifest "
            f"offsets, and hardcoding them here would drift the first time the "
            f"format moved. Check out the tt-oca-manifest submodule under "
            f"bootrom/prod/tools/."
        )
    spec = importlib.util.spec_from_file_location("_oca_constants", _OCA_CONSTANTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


K = _load_oca_constants()

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

# A digest field is 64 bytes wide with the SHA-256 in the low 32 and the rest
# 0x00, so writing one means writing 32 bytes and leaving the tail alone.
DIGEST_LEN = 32

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


def signed_region_hash(buf: bytes, base: int) -> bytes:
    """SHA-256 over the manifest's signed region, whichever variant it is."""
    end = variant_at(buf, base).signed_region_end
    return hashlib.sha256(bytes(buf[base : base + end])).digest()


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
    stored = bytes(buf[base + OFF_MANIFEST_HASH : base + OFF_MANIFEST_HASH + DIGEST_LEN])
    calc = signed_region_hash(buf, base)
    if stored != calc:
        raise AssertionError(
            f"{slot} manifest_hash does not equal "
            f"sha256(body[0:{v.signed_region_end}]) (stored {stored.hex()}, computed "
            f"{calc.hex()}); the signed boundary or the hash offset in "
            f"sep_oca_mutate no longer matches the packer"
        )


def rehash(buf: bytearray, slot: str) -> None:
    """Recompute ``manifest_hash`` after a mutation inside the signed region.

    Writes the 32-byte digest and leaves the field's zero tail alone.
    """
    require_classic(buf, slot)
    base = slot_base(slot)
    buf[base + OFF_MANIFEST_HASH : base + OFF_MANIFEST_HASH + DIGEST_LEN] = signed_region_hash(
        buf, base
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


def _selftest() -> int:
    """Check the layout assumptions against every packed image on disk."""
    build = _SEP_ROOT / "bootrom" / "prod" / "build"
    images = sorted(build.glob("oca_*_boot.bin"))
    if not images:
        print(f"no packed images in {build}; run `make oca-images` first")
        return 1
    print(f"constants from {_OCA_CONSTANTS}")
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
            classic += 1
            print(f"  ok   {describe(buf, 'primary')}")
        except AssertionError as exc:
            print(f"  FAIL {img.name}: {exc}")
            bad += 1
    print(f"\n{len(images)} image(s): {classic} classic, {pqc} pqc, {bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
