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

DEMOTION AND SECURE-BOOT POLICY ARE SIGNED. ``demotion_control`` (offset 172)
and ``secure_boot_control`` (182) are inside the signed region, so a test that
needs a manifest which *requests* a policy should get it from the pack config
rather than by mutation. Mutation here is for values that must be refused.

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

Run ``python3 sep_manifest_mutate.py`` to check the layout assumptions against every
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
# Dependency order: constants, then validators, then toc, which payload
# imports, then manifest.
_OCA_MODULES = ("constants", "validators", "toc", "payload", "manifest")


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
    return loaded["constants"], loaded["manifest"], loaded["payload"]


K, MF, PF = _load_oca()

BUILD_DIR = _SEP_ROOT / "bootrom" / "prod" / "build"

# Slot offsets in the packed image, matching the ROM's compiled-in
# PRIMARY_MANIFEST_OFFSET / BACKUP_MANIFEST_OFFSET, and asserted against the
# shipped image by verify_layout().
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
            f"classic-only because constants.py publishes no per-field PQC "
            f"offsets. Geometry (slot_span, erase_slot) works for both."
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


def rom_key_image(index: int) -> Path:
    """Packed flash image whose BOTH slots are signed by ROM key slot ``index``.

    Slot 0 is the shipped secure-boot image; slots 1-5 are the per-slot images
    2166927ea added so an off-by-one in slot resolution cannot match a digest by
    accident. Pair with :func:`graft_slot` to build a mixed image: one slot anchored
    on a chosen key, the other left as it shipped.
    """
    if not 0 <= index < PUBK_SEL_NUM_ROM_KEYS:
        raise ValueError(f"ROM key slot {index} is outside 0..{PUBK_SEL_NUM_ROM_KEYS - 1}")
    name = "oca_secure_boot.bin" if index == 0 else f"oca_rom_key{index}_boot.bin"
    p = BUILD_DIR / name
    if not p.is_file():
        raise AssertionError(f"{p} not found; run `make oca-images` in bootrom/prod")
    return p


def graft_slot(dst: bytearray, src: bytes, slot: str) -> tuple[int, int]:
    """Replace one slot of ``dst`` with the same slot of ``src``. Returns the span.

    A whole slot moves, manifest and payload together, so what lands is a slot that
    was signed as a unit by whichever key packed ``src`` -- it verifies rather than
    going stale, which a field-level rewrite of the same selector cannot do. That is
    the difference between proving the ROM refuses an authorized key it was told to
    revoke and proving only that it refuses a key whose signature no longer checks.

    Both images must devote the same byte range to the slot, which the packer's
    shared combined layout guarantees; a payload offset is stored manifest-relative
    (see :func:`sep_payload_mutate.payload_base`), so the grafted slot stays internally
    consistent at its new home.
    """
    d_start, d_end = slot_span(dst, slot)
    s_start, s_end = slot_span(src, slot)
    if (d_start, d_end) != (s_start, s_end):
        raise AssertionError(
            f"{slot} slot occupies 0x{d_start:x}..0x{d_end:x} in the destination but "
            f"0x{s_start:x}..0x{s_end:x} in the source; the two images no longer share "
            f"the packer's combined layout, so grafting would corrupt both slots"
        )
    dst[d_start:d_end] = src[s_start:s_end]
    return d_start, d_end


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
            f"sep_manifest_mutate no longer matches the packer"
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
    """One-line summary of a slot, for test log lines. Works for either variant.

    Reports an unrecognised magic rather than raising on it: a caller logging a
    slot it has just corrupted on purpose needs the description in exactly that
    case, and a diagnostic that refuses to describe a malformed image is of no
    use where it matters most.
    """
    base = slot_base(slot)
    magic = bytes(buf[base : base + 4])
    v = next((x for x in _VARIANTS if magic == x.magic), None)
    if v is None:
        return f"{slot}@0x{base:x} magic={magic!r}, not a packed OCA manifest"
    out = f"{slot}@0x{base:x} {v.format_name} body={v.body_size}"
    if v.magic == K.OCAC_MAGIC:
        digest = bytes(buf[base + OFF_MANIFEST_HASH : base + OFF_MANIFEST_HASH + 8])
        out += (
            f" sig_type={signature_type(buf, slot)}"
            f" sig_size={signature_size(buf, slot)} hash={digest.hex()}..."
        )
    return out


# ---------------------------------------------------------------------------
# ROM error codes
# ---------------------------------------------------------------------------
# The ROM prints a rejected slot's reason as MANIFEST_ERR=<code>, where the code
# is OCA_BOOT_ERR_BASE | oca_result_t (oca_boot.h). Both halves are parsed: the
# result enum is long, renumbers as the library grows, and a copied value fails
# a test for the wrong reason -- it reads as "rejected for the planted defect"
# while actually meaning "rejected for something else".
_OCA_BOOT_H = _SEP_ROOT / "bootrom" / "prod" / "include" / "oca_boot.h"
_OCA_VALIDATOR_H = _OCA_SRC.parent.parent / "validators" / "oca" / "lib" / "oca_validator.h"


def _c_define(header: Path, name: str) -> int:
    """Value of a simple ``#define NAME <int>`` in a C header.

    Used for the few bit definitions constants.py does not publish. Parsed
    rather than copied for the same reason the offsets are: a literal here goes
    stale silently.
    """
    import re

    if not header.is_file():
        raise ImportError(f"{header} not found; it defines {name}")
    m = re.search(rf"^#define\s+{name}\s+(0[xX][0-9a-fA-F]+|\d+)", header.read_text(), re.M)
    if m is None:
        raise ImportError(f"{header} does not define {name}")
    return int(m.group(1), 0)


def oca_result(name: str) -> int:
    """Value of an ``OCA_FAIL_*`` / ``OCA_OK`` enumerator, by name."""
    import re

    if not _OCA_VALIDATOR_H.is_file():
        raise ImportError(f"{_OCA_VALIDATOR_H} not found; it defines the result enum")
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*(\d+)", _OCA_VALIDATOR_H.read_text(), re.M)
    if m is None:
        raise AssertionError(f"{_OCA_VALIDATOR_H} does not define {name}")
    return int(m.group(1))


def boot_err(result_name: str) -> int:
    """The ``MANIFEST_ERR=`` code the ROM prints for one validator result.

    For a rejection the library decided. The ROM's own refusals are separate
    codes, not compositions of a result -- see :func:`rom_boot_err`.
    """
    return _c_define(_OCA_BOOT_H, "OCA_BOOT_ERR_BASE") | oca_result(result_name)


_OCA_BOOT_C = _SEP_ROOT / "bootrom" / "prod" / "src" / "oca_boot.c"
_STATUS_VALUES_H = _SEP_ROOT / "bootrom" / "prod" / "include" / "status_values.h"


def rom_status_for_result(boot_error: int) -> int:
    """The ``SEP_MSG_*`` value the ROM reports for one ``MANIFEST_ERR=`` code.

    The console code and the status ring live in DIFFERENT spaces: the console
    carries ``OCA_BOOT_ERR_BASE | oca_result_t`` while the ring carries
    ``STATUS_ENCODE(type, SEP_MSG_*)``. ``status_for_result()`` in oca_boot.c is
    the only bridge, so it is parsed rather than mirrored -- masking the console
    code and calling the low half a status is how a test ends up asserting on a
    value the ROM never reports.

    Only the RESULT range crosses that bridge. rom_manifest_boot() re-reports a
    slot's verdict through status_for_result() under
    ``(last_err & 0xFFFFFF00) == OCA_BOOT_ERR_BASE``, so the ROM's own
    ``0x000301xx`` codes -- no BL1 in the TOC, a BL1 placement outside SRAM, a
    refused storage read -- skip it entirely and reach the ring only as the
    generic ``SEP_MSG_MANIFEST_LOAD_FAILED`` that follows. This mirrors that
    guard rather than reproducing the arithmetic: a 0x000301xx code has no
    oca_result_t to look up, and looking one up anyway is what made this raise
    on sep_bl1_entry_invalid_test.
    """
    import re

    if not _OCA_BOOT_C.is_file():
        raise ImportError(f"{_OCA_BOOT_C} not found; it defines status_for_result()")
    body = _OCA_BOOT_C.read_text()
    m = re.search(r"status_for_result\s*\([^)]*\)\s*\{(.*?)\n\}", body, re.S)
    if m is None:
        raise AssertionError("status_for_result() not found in oca_boot.c")

    # The ROM's guard, in the ROM's own terms. Masked with 0xFF like oca_boot.c,
    # not 0xFFFF: the low BYTE is the oca_result_t, and the byte above it is what
    # separates a library verdict from one of the ROM's own codes.
    if (boot_error & 0xFFFFFF00) != _c_define(_OCA_BOOT_H, "OCA_BOOT_ERR_BASE"):
        return _c_define(_STATUS_VALUES_H, "SEP_MSG_MANIFEST_LOAD_FAILED")

    want = boot_error & 0xFF
    pending: list[str] = []
    for line in m.group(1).splitlines():
        case = re.search(r"case\s+(OCA_FAIL_[A-Z0-9_]+)\s*:", line)
        if case:
            pending.append(case.group(1))
            continue
        ret = re.search(r"return\s+(SEP_MSG_[A-Z0-9_]+)\s*;", line)
        if ret:
            for name in pending:
                if oca_result(name) == want:
                    return _c_define(_STATUS_VALUES_H, ret.group(1))
            pending = []
    raise AssertionError(
        f"status_for_result() maps no OCA_FAIL_* with value {want} "
        f"(from boot error {boot_error:#010x})"
    )


def rom_boot_err(name: str) -> int:
    """One of the ROM's own ``OCA_BOOT_ERR_*`` codes, by name.

    These are whole constants in oca_boot.h rather than OCA_BOOT_ERR_BASE OR-ed
    with a validator result: they cover what the ROM refuses on its own account
    (no BL1 in the TOC, a placement outside the permitted regions, a storage
    read failure) and occupy 0x000301xx, clear of the result range.
    """
    return _c_define(_OCA_BOOT_H, name)


# ---------------------------------------------------------------------------
# Structural and anti-rollback fields
# ---------------------------------------------------------------------------
OFF_MAGIC = K.OFF_BOOT_MANIFEST_MAGIC
OFF_VERSION_MAJOR = K.OFF_MANIFEST_VERSION_MAJOR
OFF_VERSION_MINOR = K.OFF_MANIFEST_VERSION_MINOR
OFF_MANIFEST_LENGTH = K.OFF_MANIFEST_LENGTH
OFF_SECURITY_VERSION = K.OFF_MANIFEST_SECURITY_VERSION
SECURITY_VERSION_LEN = 16

# manifest_length must equal the variant's body size at every minor version.
MANIFEST_SIZE = BODY_SIZE
MANIFEST_MAJOR_VERSION = 1
# The consumer's own copy of the body size, which is what the ROM enforces.
CONSUMER_BODY_SIZE = _c_define(
    _OCA_VALIDATOR_H.with_name("oca_layout_classic.h"), "OCA_CLASSIC_BODY_SIZE"
)
# Bytes the ROM reads from a slot before it knows the body size.
MANIFEST_PEEK_MIN = _c_define(_OCA_VALIDATOR_H, "OCA_MANIFEST_PEEK_MIN")


def manifest_version(buf: bytes, slot: str) -> tuple[int, int]:
    """Return the OCA CLASSIC ``(major, minor)`` format version."""
    require_classic(buf, slot)
    base = slot_base(slot)
    return (
        int.from_bytes(
            bytes(buf[base + OFF_VERSION_MAJOR : base + OFF_VERSION_MAJOR + 2]), "little"
        ),
        int.from_bytes(
            bytes(buf[base + OFF_VERSION_MINOR : base + OFF_VERSION_MINOR + 2]), "little"
        ),
    )


def set_manifest_version(
    buf: bytearray,
    slot: str,
    *,
    major: int | None = None,
    minor: int | None = None,
) -> tuple[int, int]:
    """Set the OCA CLASSIC format version and refresh ``manifest_hash``."""
    current_major, current_minor = manifest_version(buf, slot)
    new_major = current_major if major is None else major
    new_minor = current_minor if minor is None else minor
    if not 0 <= new_major <= 0xFFFF or not 0 <= new_minor <= 0xFFFF:
        raise ValueError("manifest version components are 16 bits")
    base = slot_base(slot)
    buf[base + OFF_VERSION_MAJOR : base + OFF_VERSION_MAJOR + 2] = new_major.to_bytes(2, "little")
    buf[base + OFF_VERSION_MINOR : base + OFF_VERSION_MINOR + 2] = new_minor.to_bytes(2, "little")
    rehash(buf, slot)
    return new_major, new_minor


def manifest_length(buf: bytes, slot: str) -> int:
    """Return the declared OCA manifest body length."""
    require_classic(buf, slot)
    base = slot_base(slot) + OFF_MANIFEST_LENGTH
    return int.from_bytes(bytes(buf[base : base + 4]), "little")


def set_manifest_length(buf: bytearray, slot: str, value: int) -> int:
    """Set the declared OCA body length and refresh ``manifest_hash``."""
    require_classic(buf, slot)
    if not 0 <= value <= 0xFFFF_FFFF:
        raise ValueError("manifest_length is 32 bits")
    base = slot_base(slot) + OFF_MANIFEST_LENGTH
    buf[base : base + 4] = value.to_bytes(4, "little")
    rehash(buf, slot)
    return value


def manifest_hash(buf: bytes, slot: str) -> bytes:
    """Return the SHA-256 portion of the padded OCA ``manifest_hash`` field."""
    base = slot_base(slot) + OFF_MANIFEST_HASH
    return bytes(buf[base : base + DIGEST_LEN])


def signed_region_hash(buf: bytes, slot: str) -> bytes:
    """Return SHA-256 over the OCA variant's signed region."""
    base = slot_base(slot)
    variant = variant_at(buf, base)
    return hashlib.sha256(bytes(buf[base : base + variant.signed_region_end])).digest()


def corrupt_manifest_hash(
    buf: bytearray,
    slot: str,
    *,
    byte_index: int = 0,
    xor_mask: int = 0xFF,
) -> None:
    """Corrupt the stored digest without changing the signed region."""
    require_classic(buf, slot)
    if not 0 <= byte_index < DIGEST_LEN:
        raise ValueError(f"manifest_hash digest is {DIGEST_LEN} bytes")
    if not 0 < xor_mask <= 0xFF:
        raise ValueError("xor_mask must be a non-zero byte")
    buf[slot_base(slot) + OFF_MANIFEST_HASH + byte_index] ^= xor_mask


def break_magic(buf: bytearray, slot: str, value: bytes = b"\x99\x99\x99\x99") -> bytes:
    """Corrupt a slot's magic so the ROM refuses it. Returns what was written.

    The standard primary->backup failover trigger. Deliberately does NOT rehash:
    the magic leads the body and ``oca_peek_manifest`` reads it before anything
    reads or hashes the rest, so the slot is rejected before the stale hash is
    ever examined. Rehashing is also impossible after the fact -- every helper
    here resolves the variant from the magic.
    """
    variant_at(buf, slot_base(slot))  # a valid manifest really was here
    if len(value) != 4:
        raise ValueError("magic is 4 bytes")
    if value in (K.OCAC_MAGIC, K.OCAP_MAGIC):
        raise ValueError(f"{value!r} is a valid magic; that is not a mutation")
    base = slot_base(slot) + OFF_MAGIC
    buf[base : base + 4] = value
    return value


def set_signature_type(buf: bytearray, slot: str, value: int) -> int:
    """Write ``signature_type_classic``. Returns the value written.

    Inside the signed region, so this rehashes. The ROM accepts only RSA-3072
    (SEP-ROM-SB-090), and the validator refuses anything it cannot verify, so
    every other value is a rejection rather than an alternative algorithm.
    """
    require_classic(buf, slot)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"signature_type is one byte, got {value}")
    buf[slot_base(slot) + OFF_SIGNATURE_TYPE] = value
    rehash(buf, slot)
    return value


def security_version(buf: bytes, slot: str) -> int:
    """``manifest_security_version`` as a 128-bit integer.

    A FLAG FIELD, not a counter. Anti-rollback requires the manifest to be a bit
    superset of the device-stored value -- ``(device & ~manifest) == 0`` -- so a
    manifest fails by *omitting* a flag the device already has, not by carrying a
    smaller number.
    """
    require_classic(buf, slot)
    base = slot_base(slot) + OFF_SECURITY_VERSION
    return int.from_bytes(bytes(buf[base : base + SECURITY_VERSION_LEN]), "little")


def set_security_version(buf: bytearray, slot: str, value: int) -> int:
    """Write the 128-bit security-version flag field. Returns what was written."""
    require_classic(buf, slot)
    mask = (1 << (8 * SECURITY_VERSION_LEN)) - 1
    value &= mask
    base = slot_base(slot) + OFF_SECURITY_VERSION
    buf[base : base + SECURITY_VERSION_LEN] = value.to_bytes(SECURITY_VERSION_LEN, "little")
    rehash(buf, slot)
    return value


def clear_security_version_bit(buf: bytearray, slot: str, bit: int) -> int:
    """Clear one security-version flag, i.e. plant an anti-rollback failure.

    This is the rollback stimulus under the superset rule: the device keeps a
    flag the manifest no longer asserts. Clearing a bit the device does not have
    set proves nothing, so the bit has to be one the OTP carries.
    """
    require_classic(buf, slot)
    if not 0 <= bit < 8 * SECURITY_VERSION_LEN:
        raise ValueError(f"bit {bit} is outside the {8 * SECURITY_VERSION_LEN}-bit field")
    return set_security_version(buf, slot, security_version(buf, slot) & ~(1 << bit))


# ---------------------------------------------------------------------------
# Usage constraints
# ---------------------------------------------------------------------------
# A manifest states which constraints it wants enforced in selector_bits, then
# supplies each selected constraint's value in its own field. The ROM fails a
# slot whose selected constraint it cannot evaluate (SEP-ROM-MAN-040), so
# selecting a bit and leaving its field unset is a rejection, not a default.
OFF_SELECTOR_BITS = K.OFF_SELECTOR_BITS
SELECTOR_BITS_LEN = 16
SELECTOR_BITS_USED_LIMIT = K.SELECTOR_BITS_USED_LIMIT

# Selector bit base+i enables byte i of a 32-byte identity field; constants.py lacks the bases.
OFF_IDENTITY = {
    "chiplet": K.OFF_CHIPLET_ID,
    "package": K.OFF_PACKAGE_ID,
    "system": K.OFF_SYSTEM_ID,
}
IDENTITY_LEN = K.CHIPLET_ID_SIZE
SELECTOR_BIT_IDENTITY_BASE = {"chiplet": 0, "package": 32, "system": 64}
if {K.CHIPLET_ID_SIZE, K.PACKAGE_ID_SIZE, K.SYSTEM_ID_SIZE} != {32}:
    raise ImportError(
        "an identity field is no longer 32 bytes, so a 32-bit per-byte selector mask "
        "no longer covers it; re-derive SELECTOR_BIT_IDENTITY_BASE from selector.c"
    )

# A lifecycle constraint is per identity scope: three fields, each with its own
# selector bit.
OFF_LIFECYCLE_STATES = {
    "chiplet": K.OFF_LIFECYCLE_CHIPLET_STATES,
    "package": K.OFF_LIFECYCLE_PACKAGE_STATES,
    "system": K.OFF_LIFECYCLE_SYSTEM_STATES,
}
SELECTOR_BIT_LIFECYCLE = {
    "chiplet": K.SELECTOR_BIT_LIFECYCLE_CHIPLET,
    "package": K.SELECTOR_BIT_LIFECYCLE_PACKAGE,
    "system": K.SELECTOR_BIT_LIFECYCLE_SYSTEM,
}
LIFECYCLE_STATE_BITS = dict(K.LIFECYCLE_STATE_NAMES)
LIFECYCLE_STATES_VALID_MASK = K.LIFECYCLE_STATES_VALID_MASK
SHIPPED_SELECTOR_BITS = 0
SHIPPED_IDENTITY_BYTE = K.MANIFEST_UNUSED_BYTE

# Demotion is a standalone u16 here, not a selector bit plus a flags bit. Its
# four bits match oca_boot.h's OCA_DEMOTE_* exactly.
OFF_DEMOTION_CONTROL = K.OFF_DEMOTION_CONTROL
DEMOTION_BITS = dict(K.DEMOTION_CONTROL_FLAG_NAMES)
DEMOTION_CONTROL_VALID_MASK = K.DEMOTION_CONTROL_VALID_MASK

OFF_SECURE_BOOT_CONTROL = K.OFF_SECURE_BOOT_CONTROL
OFF_ENCRYPTION_IV = K.OFF_ENCRYPTION_IV
OFF_ENCRYPTION_KDF_INPUT = K.OFF_ENCRYPTION_KDF_INPUT
_OCA_LAYOUT_H = _OCA_SRC.parent.parent / "validators" / "oca" / "lib" / "oca_layout.h"


SECURE_BOOT_ENFORCED_BIT = _c_define(_OCA_LAYOUT_H, "OCA_SECURE_BOOT_ENFORCED_BIT")


def selector_bits(buf: bytes, slot: str) -> int:
    """``selector_bits`` as an integer. 128 bits wide here, not 64."""
    require_classic(buf, slot)
    base = slot_base(slot) + OFF_SELECTOR_BITS
    return int.from_bytes(bytes(buf[base : base + SELECTOR_BITS_LEN]), "little")


def _put_selector_bits(buf: bytearray, slot: str, bits: int) -> None:
    base = slot_base(slot) + OFF_SELECTOR_BITS
    buf[base : base + SELECTOR_BITS_LEN] = bits.to_bytes(SELECTOR_BITS_LEN, "little")


def set_selector_bit(buf: bytearray, slot: str, bit: int, value: bool) -> int:
    """Set or clear one selector bit. Returns the resulting bitmap."""
    require_classic(buf, slot)
    if not 0 <= bit < 8 * SELECTOR_BITS_LEN:
        raise ValueError(f"selector bit {bit} is outside the 128-bit field")
    bits = selector_bits(buf, slot)
    bits = (bits | (1 << bit)) if value else (bits & ~(1 << bit))
    _put_selector_bits(buf, slot, bits)
    rehash(buf, slot)
    return bits


def _reseal(buf: bytearray, slot: str) -> None:
    # Deferred import: sep_payload_mutate imports this module.
    from env import sep_payload_mutate as pm

    pm.reseal(buf, slot, check_toc=not pm.is_encrypted(buf, slot))


def _identity_field_mask(kind: str) -> int:
    if kind not in OFF_IDENTITY:
        raise ValueError(f"kind must be one of {sorted(OFF_IDENTITY)}, got {kind!r}")
    return ((1 << IDENTITY_LEN) - 1) << SELECTOR_BIT_IDENTITY_BASE[kind]


def selector_mask(kind: str, byte_index: int) -> int:
    _identity_field_mask(kind)
    if not 0 <= byte_index < IDENTITY_LEN:
        raise ValueError(f"{kind} identity has {IDENTITY_LEN} bytes, not index {byte_index}")
    return 1 << (SELECTOR_BIT_IDENTITY_BASE[kind] + byte_index)


def identity(buf: bytes, slot: str, kind: str) -> bytes:
    require_classic(buf, slot)
    _identity_field_mask(kind)
    base = slot_base(slot) + OFF_IDENTITY[kind]
    return bytes(buf[base : base + IDENTITY_LEN])


def verify_identity_layout(buf: bytes, slot: str) -> None:
    bits = selector_bits(buf, slot)
    for kind in OFF_IDENTITY:
        field = identity(buf, slot, kind)
        stray = [
            i
            for i in range(IDENTITY_LEN)
            if not bits & selector_mask(kind, i) and field[i] != SHIPPED_IDENTITY_BYTE
        ]
        if stray:
            raise AssertionError(
                f"{slot} {kind} identity has non-0x{SHIPPED_IDENTITY_BYTE:02x} bytes at "
                f"unselected positions {stray} ({field.hex()}); OFF_IDENTITY looks wrong"
            )


def set_identity(buf: bytearray, slot: str, kind: str, value: bytes, mask: int) -> None:
    require_classic(buf, slot)
    field_mask = _identity_field_mask(kind)
    if len(value) != IDENTITY_LEN:
        raise ValueError(f"{kind} identity is {IDENTITY_LEN} bytes, got {len(value)}")
    if mask == 0 or mask & ~field_mask:
        raise ValueError(
            f"mask 0x{mask:x} must select at least one {kind} byte and nothing outside "
            f"0x{field_mask:x}; an empty selection leaves the constraint unchecked"
        )
    filled = bytes(
        value[i] if mask & selector_mask(kind, i) else SHIPPED_IDENTITY_BYTE
        for i in range(IDENTITY_LEN)
    )
    base = slot_base(slot) + OFF_IDENTITY[kind]
    buf[base : base + IDENTITY_LEN] = filled
    _put_selector_bits(buf, slot, (selector_bits(buf, slot) & ~field_mask) | mask)
    verify_identity_layout(buf, slot)
    _reseal(buf, slot)


def set_lifecycle_constraint(
    buf: bytearray, slot: str, allowed: int, level: str = "chiplet"
) -> None:
    # The SEP reports only a chiplet lifecycle; the ROM refuses package/system constraints.
    require_classic(buf, slot)
    if level not in OFF_LIFECYCLE_STATES:
        raise ValueError(f"level must be one of {sorted(OFF_LIFECYCLE_STATES)}, got {level!r}")
    if not 0 <= allowed <= LIFECYCLE_STATES_VALID_MASK:
        raise ValueError(
            f"allowed 0x{allowed:x} sets bits outside 0x{LIFECYCLE_STATES_VALID_MASK:x}"
        )
    verify_usage_constraints_layout(buf, slot)
    base = slot_base(slot) + OFF_LIFECYCLE_STATES[level]
    buf[base : base + 4] = allowed.to_bytes(4, "little")
    _put_selector_bits(buf, slot, selector_bits(buf, slot) | (1 << SELECTOR_BIT_LIFECYCLE[level]))
    _reseal(buf, slot)


def lifecycle_states(buf: bytes, slot: str, scope: str = "chiplet") -> int:
    """The lifecycle-state bitmap for one identity scope (u32)."""
    require_classic(buf, slot)
    if scope not in OFF_LIFECYCLE_STATES:
        raise ValueError(f"scope must be one of {sorted(OFF_LIFECYCLE_STATES)}, got {scope!r}")
    base = slot_base(slot) + OFF_LIFECYCLE_STATES[scope]
    return int.from_bytes(bytes(buf[base : base + 4]), "little")


def set_lifecycle_states(buf: bytearray, slot: str, value: int, scope: str = "chiplet") -> int:
    """Write one scope's lifecycle-state bitmap. Returns what was written.

    Does not touch the selector bit: whether the constraint is enforced and what
    it permits are separate stimuli, and a test usually wants to vary one.
    """
    require_classic(buf, slot)
    if scope not in OFF_LIFECYCLE_STATES:
        raise ValueError(f"scope must be one of {sorted(OFF_LIFECYCLE_STATES)}, got {scope!r}")
    base = slot_base(slot) + OFF_LIFECYCLE_STATES[scope]
    buf[base : base + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    rehash(buf, slot)
    return value & 0xFFFFFFFF


def demotion_control(buf: bytes, slot: str) -> int:
    """``demotion_control`` (u16). Bits per DEMOTION_BITS."""
    require_classic(buf, slot)
    base = slot_base(slot) + OFF_DEMOTION_CONTROL
    return int.from_bytes(bytes(buf[base : base + 2]), "little")


def set_demotion_bit(buf: bytearray, slot: str, name: str, value: bool) -> int:
    """Set or clear one demotion-control bit by name. Returns the field."""
    require_classic(buf, slot)
    if name not in DEMOTION_BITS:
        raise ValueError(f"name must be one of {sorted(DEMOTION_BITS)}, got {name!r}")
    bit = DEMOTION_BITS[name]
    field = demotion_control(buf, slot)
    field = (field | (1 << bit)) if value else (field & ~(1 << bit))
    base = slot_base(slot) + OFF_DEMOTION_CONTROL
    buf[base : base + 2] = (field & 0xFFFF).to_bytes(2, "little")
    rehash(buf, slot)
    return field & 0xFFFF


def set_demotion(
    buf: bytearray,
    slot: str,
    *,
    bl1_valid: bool = False,
    bl1_enable: bool = False,
    bl2_valid: bool = False,
    bl2_enable: bool = False,
) -> int:
    """Write the whole demotion_control field at once. Returns the field.

    One call rather than four set_demotion_bit() calls: the bits are one
    decision, and setting them separately would rehash once per bit and leave
    intermediate states that mean something different from the intended one.
    Bits not named are cleared, so the field says exactly what the caller asked
    for and nothing carried over from the shipped image.
    """
    require_classic(buf, slot)
    field = 0
    for name, on in (
        ("BL1_DEMOTION_VALID", bl1_valid),
        ("BL1_DEMOTION_ENABLE", bl1_enable),
        ("BL2_DEMOTION_VALID", bl2_valid),
        ("BL2_DEMOTION_ENABLE", bl2_enable),
    ):
        if on:
            field |= 1 << DEMOTION_BITS[name]
    base = slot_base(slot) + OFF_DEMOTION_CONTROL
    buf[base : base + 2] = field.to_bytes(2, "little")
    rehash(buf, slot)
    return field


def secure_boot_control(buf: bytes, slot: str) -> int:
    """``secure_boot_control`` (u8). Bit 0 is the signed enforcement request."""
    require_classic(buf, slot)
    return buf[slot_base(slot) + OFF_SECURE_BOOT_CONTROL]


def clear_secure_boot(buf: bytearray, slot: str) -> None:
    """Make a slot validly UNSIGNED, not merely un-enforced.

    Clearing the enforced bit alone produces a manifest the ROM refuses: with
    secure boot off the parser requires the slot to carry no crypto material at
    all, and returns OCA_FAIL_SECURE_BOOT_INVARIANT if the signature, public key,
    key-select, or any of the type/encoding bytes is non-zero. A test that only
    cleared the bit would see a manifest rejection where it expected its own
    stimulus.

    So this zeroes the whole set, which is what the packer emits for
    ``secure_boot: 0``. The signature is outside the signed region and the rest
    are inside it; the rehash at the end covers them.
    """
    require_classic(buf, slot)
    base = slot_base(slot)
    for off, length in (
        (OFF_SIGNATURE, K.SIGNATURE_CLASSIC_SIZE),
        (OFF_PUBLIC_KEY, K.PUBLIC_KEY_CLASSIC_SIZE),
        (OFF_PUBLIC_KEY_SEL, PUBLIC_KEY_SEL_LEN),
    ):
        buf[base + off : base + off + length] = bytes(length)
    for off in (
        OFF_SIGNATURE_TYPE,
        K.OFF_SIGNATURE_ENCODING_CLASSIC,
        OFF_PUBLIC_KEY_ENCODING,
        OFF_SECURE_BOOT_CONTROL,
    ):
        buf[base + off] = 0
    rehash(buf, slot)


def set_secure_boot_enforced(buf: bytearray, slot: str, value: bool) -> int:
    """Set or clear the signed secure-boot request. Returns the field.

    Inside the signed region, so this rehashes -- and the ROM checks the hash
    before the signature, which is what makes clearing the bit a rejected
    manifest rather than a manifest that boots unverified.
    """
    require_classic(buf, slot)
    field = secure_boot_control(buf, slot)
    field = (
        (field | SECURE_BOOT_ENFORCED_BIT) if value else (field & ~SECURE_BOOT_ENFORCED_BIT)
    ) & 0xFF
    buf[slot_base(slot) + OFF_SECURE_BOOT_CONTROL] = field
    rehash(buf, slot)
    return field


def set_secure_boot_control(buf: bytearray, slot: str, value: int) -> int:
    """Write the whole ``secure_boot_control`` byte. Returns the previous value.

    For stimuli that need a class bit without the enforced bit, which
    :func:`set_secure_boot_enforced` cannot express because it preserves the
    class bits it finds. Inside the signed region, so this rehashes.
    """
    require_classic(buf, slot)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"secure_boot_control is one byte, got 0x{value:x}")
    before = secure_boot_control(buf, slot)
    buf[slot_base(slot) + OFF_SECURE_BOOT_CONTROL] = value
    rehash(buf, slot)
    return before


def verify_usage_constraints_layout(buf: bytes, slot: str) -> None:
    """Assert the constraint fields satisfy the format's own invariants.

    A wrong offset lands on neighbouring bytes, which fail these masks -- but
    only if those bytes are non-zero. The images this tree packs currently select
    no constraints at all (selector_bits, all three lifecycle_states and
    demotion_control are zero), so on them this is a weak anchor: it catches an
    offset that lands on a populated field such as chiplet_id or a version
    range, and not one that lands on other zeroes. It becomes a real check on the
    images the demotion and lifecycle families need, which do select
    constraints. Treat it as an invariant check, not a value anchor.
    """
    require_classic(buf, slot)
    bits = selector_bits(buf, slot)
    if bits & K.SELECTOR_BITS_RESERVED_MASK:
        raise AssertionError(
            f"{slot} selector_bits 0x{bits:032x} sets reserved bits above "
            f"{SELECTOR_BITS_USED_LIMIT}; OFF_SELECTOR_BITS looks wrong"
        )
    for scope in OFF_LIFECYCLE_STATES:
        lc = lifecycle_states(buf, slot, scope)
        if lc & ~LIFECYCLE_STATES_VALID_MASK:
            raise AssertionError(
                f"{slot} {scope} lifecycle_states 0x{lc:08x} sets bits outside "
                f"0x{LIFECYCLE_STATES_VALID_MASK:x}; its offset looks wrong"
            )
    dc = demotion_control(buf, slot)
    if dc & ~DEMOTION_CONTROL_VALID_MASK:
        raise AssertionError(
            f"{slot} demotion_control 0x{dc:04x} sets bits outside "
            f"0x{DEMOTION_CONTROL_VALID_MASK:x}; OFF_DEMOTION_CONTROL looks wrong"
        )


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

# Selection kinds, mapped onto bitmap slots by key_slot_for().
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

_BOOTROM_PROD = _SEP_ROOT / "bootrom" / "prod"
# key_digests.c is generated into the ROM's build directory, so read it from
# whichever variant this run built. BUILD_DIR selects the SPI transport, not the
# anchors, so all three carry the same key set and the first present one answers.
_KEY_DIGESTS_BUILD_DIRS = ("build", "build_pio")
_OCA_PLATFORM_C = _BOOTROM_PROD / "src" / "oca_platform.c"


def _key_digests_c():
    """Locate the generated ROM key digest table."""
    for build_dir in _KEY_DIGESTS_BUILD_DIRS:
        candidate = _BOOTROM_PROD / build_dir / "key_digests.c"
        if candidate.is_file():
            return candidate
    searched = ", ".join(f"{d}/" for d in _KEY_DIGESTS_BUILD_DIRS)
    raise AssertionError(
        f"key_digests.c not found under {_BOOTROM_PROD} ({searched}); "
        "it is generated by the ROM build and holds the provisioned digests"
    )


# The slot bitmap's regions, as the ROM's own dispatch divides them. Each names a
# DIFFERENT refusal, so a test that means one must not land in another:
#   [0, CLASSICAL_LAST]               provisioned ROM classical keys
#   (CLASSICAL_LAST, CLASSICAL_RSVD]  PUBK_SLOT_RESERVED   -- the ROM octet's top two
#   (CLASSICAL_RSVD, PQC_LAST]        PUBK_SLOT_PQC_UNSUPPORTED
#   (PQC_LAST, PQC_RESERVED_LAST]     PUBK_SLOT_RESERVED   -- the PQC octet's top two
#   (PQC_RESERVED_LAST, SLOT_MAX]     fuse-held chiplet keys
#   (SLOT_MAX, ...)                   PUBK_SLOT_RESERVED   -- [31:26]
#
# PUBK_SLOT_UNPROVISIONED has no reachable slot: the classical band and the
# digest table are the same size by construction, so the ROM's NULL-digest guard
# is fail-closed defence rather than a stimulus any manifest can produce.
KEY_SLOT_ROM_CLASSICAL_LAST = _c_define(_OCA_PLATFORM_C, "OCA_KEY_SLOT_ROM_CLASSICAL_LAST")
KEY_SLOT_ROM_CLASSICAL_RESERVED_LAST = _c_define(
    _OCA_PLATFORM_C, "OCA_KEY_SLOT_ROM_CLASSICAL_RESERVED_LAST"
)
KEY_SLOT_ROM_PQC_LAST = _c_define(_OCA_PLATFORM_C, "OCA_KEY_SLOT_ROM_PQC_LAST")
KEY_SLOT_ROM_PQC_RESERVED_LAST = _c_define(_OCA_PLATFORM_C, "OCA_KEY_SLOT_ROM_PQC_RESERVED_LAST")
KEY_SLOT_MAX = _c_define(_OCA_PLATFORM_C, "OCA_KEY_SLOT_MAX")
# The boundary values a test asserts on: the smallest slot of each refusal.
# The ROM classical octet's reserved pair is the cheapest reserved stimulus --
# it needs no out-of-range index, only a slot this generation declines to assign.
KEY_SLOT_FIRST_ROM_RESERVED = KEY_SLOT_ROM_CLASSICAL_LAST + 1
KEY_SLOT_FIRST_RESERVED = KEY_SLOT_MAX + 1


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


def set_public_key_slots(buf: bytearray, slot: str, bits: tuple[int, ...]) -> tuple[int, ...]:
    """Name several key slots at once, i.e. plant the ambiguity refusal.

    The validator refuses a bitmap naming more than one anchor rather than
    picking, so this is the stimulus for that arm. One bit is a selection, not an
    ambiguity -- use :func:`set_public_key_sel` for that.
    """
    require_classic(buf, slot)
    if len(bits) < 2:
        raise ValueError("an ambiguous bitmap needs at least two slots")
    field = bytearray(PUBLIC_KEY_SEL_LEN)
    for bit in bits:
        if not 0 <= bit < 8 * PUBLIC_KEY_SEL_LEN:
            raise ValueError(f"slot {bit} is outside the {8 * PUBLIC_KEY_SEL_LEN}-bit bitmap")
        field[bit // 8] |= 1 << (bit % 8)
    base = slot_base(slot) + OFF_PUBLIC_KEY_SEL
    buf[base : base + PUBLIC_KEY_SEL_LEN] = field
    rehash(buf, slot)
    return bits


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

    text = _key_digests_c().read_text()
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


OFF_PUBLIC_KEY_SIZE = K.OFF_PUBLIC_KEY_SIZE_CLASSIC


def remove_public_key(buf: bytearray, slot: str, *, keep_size: bool) -> None:
    """Zero the classical public-key field, leaving the rest of the slot signed.

    With ``keep_size`` the field still claims its encoded length, so the slot
    passes the structural size check and reaches key authorization with an
    all-zero modulus. Without it ``public_key_size`` is zeroed too, which is what
    a manifest that never carried a key looks like, and the structural check
    refuses it first. Inside the signed region, so this rehashes.
    """
    require_classic(buf, slot)
    base = slot_base(slot)
    buf[base + OFF_PUBLIC_KEY : base + OFF_PUBLIC_KEY + K.PUBLIC_KEY_CLASSIC_SIZE] = bytes(
        K.PUBLIC_KEY_CLASSIC_SIZE
    )
    if not keep_size:
        buf[base + OFF_PUBLIC_KEY_SIZE : base + OFF_PUBLIC_KEY_SIZE + 2] = bytes(2)
    rehash(buf, slot)


def remove_signature(buf: bytearray, slot: str, *, keep_size: bool) -> None:
    """Zero the classical signature field.

    With ``keep_size`` the slot reaches the verifier carrying an all-zero
    signature. Without it ``signature_size``, which sits inside the signed region,
    is zeroed as well and the structural size check refuses the slot first. The
    signature field itself is outside the signed region; the rehash covers the
    size field.
    """
    require_classic(buf, slot)
    base = slot_base(slot)
    buf[base + OFF_SIGNATURE : base + OFF_SIGNATURE + K.SIGNATURE_CLASSIC_SIZE] = bytes(
        K.SIGNATURE_CLASSIC_SIZE
    )
    if not keep_size:
        buf[base + OFF_SIGNATURE_SIZE : base + OFF_SIGNATURE_SIZE + 2] = bytes(2)
    rehash(buf, slot)


def flip_signature_byte(
    buf: bytearray, slot: str, *, byte_index: int = 0, xor_mask: int = 0x01
) -> int:
    """XOR one signature byte. Returns the byte's offset within the field.

    No rehash: the signature sits outside the signed region, so the manifest hash
    still matches and the run reaches signature verification -- which is the
    point, since a hash mismatch would reject the image earlier and prove nothing
    about the verifier.

    The default is a single-bit flip. A minimal change is the stronger stimulus:
    it leaves the signature the right length and shape, so it exercises the
    verifier's arithmetic rather than an early structural refusal.
    """
    require_classic(buf, slot)
    span = OFF_MANIFEST_HASH - OFF_SIGNATURE
    if not 0 <= byte_index < span:
        raise ValueError(f"byte_index {byte_index} is outside the {span}-byte signature field")
    if not 0 <= xor_mask <= 0xFF or xor_mask == 0:
        raise ValueError(f"xor_mask must be a non-zero byte, got {xor_mask}")
    buf[slot_base(slot) + OFF_SIGNATURE + byte_index] ^= xor_mask
    return byte_index


def forge_pkcs1_signature(buf: bytearray, slot: str) -> bytes:
    """Replace the signature with the literal PKCS#1 v1.5 block the ROM expects.

    This is the payload of the OTBN no-op bypass. ``verify_pkcs1_v15()`` compares
    the modexp RESULT against this structure, and the result shares its DMEM
    buffer with the signature (both at ``inout``), so a modexp that never runs
    leaves exactly these bytes for the comparison to succeed against -- an
    unverified boot reported as a verified one.

    Nothing secret is used to build it: the structure is public and the digest is
    the manifest's own. That is the point. A device whose verifier actually runs
    rejects this signature, because ``sig^e mod n`` of a block nobody signed is
    not that block.

    No rehash: the signature sits outside the signed region, so the manifest hash
    still matches and the run reaches signature verification rather than being
    refused earlier.

    Returns the block written, so a caller can show what it planted.
    """
    require_classic(buf, slot)
    base = slot_base(slot)
    # The field is 512 B but the primitive is 384; the ROM converts exactly
    # OCA_RSA3072_SIGNATURE_BYTES from the start of it (rsa_verify.c,
    # bytes_to_otbn_words). A block built to the field width would put the
    # DigestInfo and digest past what the ROM ever reads, so the forgery has to
    # be the primitive's width and the tail of the field is left alone.
    sig_len = signature_size(buf, slot)
    if sig_len != 384:
        raise ValueError(f"signature_size is {sig_len}, expected 384 for RSA-3072")
    field = manifest_hash_field(buf, base)
    digest = bytes(field[:32])
    if any(field[32:]):
        raise ValueError(
            f"manifest_hash field is {len(field)} B with non-zero bytes past 32; "
            f"this helper assumes SHA-256 in the low 32 and zero padding after"
        )
    # DigestInfo for SHA-256, RFC 8017 A.2.4. The ROM holds the same 19 bytes as
    # packed words in rsa_verify.c.
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420")
    pad_len = sig_len - 3 - len(digest_info) - len(digest)
    if pad_len < 8:
        raise ValueError(f"signature is {sig_len} B, too small for a PKCS#1 block")
    block = b"\x00\x01" + b"\xff" * pad_len + b"\x00" + digest_info + digest
    if len(block) != sig_len:
        raise ValueError(f"built a {len(block)} B block for a {sig_len} B signature")
    buf[base + OFF_SIGNATURE : base + OFF_SIGNATURE + sig_len] = block
    return block


def _selftest() -> int:
    """Check the layout assumptions against every packed image on disk."""
    images = sorted(BUILD_DIR.glob("oca_*_boot.bin"))
    if not images:
        print(f"no packed images in {BUILD_DIR}; run `make oca-images` first")
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
            # Constraint fields must satisfy the format's masks, and each
            # mutator must round-trip and leave the manifest hash consistent.
            verify_usage_constraints_layout(buf, "primary")
            u = bytearray(buf)
            if (
                set_selector_bit(u, "primary", SELECTOR_BIT_LIFECYCLE["package"], True)
                & (1 << SELECTOR_BIT_LIFECYCLE["package"])
                == 0
            ):
                print(f"  FAIL {img.name}: selector bit did not set")
                bad += 1
            if (
                set_lifecycle_states(u, "primary", LIFECYCLE_STATES_VALID_MASK, "system")
                != (LIFECYCLE_STATES_VALID_MASK)
                or lifecycle_states(u, "primary", "system") != LIFECYCLE_STATES_VALID_MASK
            ):
                print(f"  FAIL {img.name}: lifecycle_states round trip")
                bad += 1
            if not set_demotion_bit(u, "primary", "BL2_DEMOTION_ENABLE", True) & (
                1 << DEMOTION_BITS["BL2_DEMOTION_ENABLE"]
            ):
                print(f"  FAIL {img.name}: demotion bit did not set")
                bad += 1
            want_sb = signature_type(buf, "primary") != SIG_TYPE_NO_SIGNATURE
            if bool(set_secure_boot_enforced(u, "primary", want_sb) & SECURE_BOOT_ENFORCED_BIT) != (
                want_sb
            ):
                print(f"  FAIL {img.name}: secure_boot_enforced did not follow")
                bad += 1
            # Every one of those rehashed, so the slot must still verify.
            verify_layout(u, "primary")
            verify_usage_constraints_layout(u, "primary")

            # break_magic makes the slot unrecognisable and leaves the hash
            # stale on purpose, so nothing that resolves the variant works after.
            b = bytearray(buf)
            break_magic(b, "primary")
            try:
                variant_at(b, slot_base("primary"))
            except AssertionError:
                pass
            else:
                print(f"  FAIL {img.name}: magic still resolved after break_magic")
                bad += 1
            if bytes(b[slot_base("backup") :]) != bytes(buf[slot_base("backup") :]):
                print(f"  FAIL {img.name}: break_magic touched the other slot")
                bad += 1

            # signature_type and the security-version flags round-trip and rehash.
            t = bytearray(buf)
            if set_signature_type(t, "primary", SIG_TYPE_ECDSA_P256) != SIG_TYPE_ECDSA_P256:
                print(f"  FAIL {img.name}: signature_type round trip")
                bad += 1
            verify_layout(t, "primary")
            sv = security_version(buf, "primary")
            t = bytearray(buf)
            set_security_version(t, "primary", sv | (1 << 7))
            if not security_version(t, "primary") & (1 << 7):
                print(f"  FAIL {img.name}: security_version bit did not set")
                bad += 1
            clear_security_version_bit(t, "primary", 7)
            if security_version(t, "primary") & (1 << 7):
                print(f"  FAIL {img.name}: security_version bit did not clear")
                bad += 1
            verify_layout(t, "primary")
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

    # Both MANIFEST_ERR spaces reach the ring. A library verdict crosses
    # status_for_result() to its own SEP_MSG_*; one of the ROM's own 0x000301xx
    # codes does not cross at all and reaches the ring only as the generic
    # SEP_MSG_MANIFEST_LOAD_FAILED. Checked here because a test that asserts the
    # wrong one still looks plausible -- the two agree on OCA_FAIL_SIGNATURE.
    load_failed = _c_define(_STATUS_VALUES_H, "SEP_MSG_MANIFEST_LOAD_FAILED")
    print("\nstatus ring mapping:")
    for name in ("OCA_FAIL_SIGNATURE", "OCA_FAIL_ROOT_KEY_REVOKED", "OCA_FAIL_SECURITY_VERSION"):
        got = rom_status_for_result(boot_err(name))
        if got == load_failed:
            print(f"  FAIL {name}: mapped to the generic code, not its own SEP_MSG_*")
            bad += 1
        else:
            print(f"  ok   {name} -> SEP_MSG 0x{got:02x}")
    for name in ("OCA_BOOT_ERR_BL1_BAD_ADDR", "OCA_BOOT_ERR_NO_BL1", "OCA_BOOT_ERR_DMA"):
        got = rom_status_for_result(rom_boot_err(name))
        if got != load_failed:
            print(
                f"  FAIL {name}: mapped to SEP_MSG 0x{got:02x}, expected the generic 0x{load_failed:02x}"
            )
            bad += 1
        else:
            print(f"  ok   {name} -> generic SEP_MSG_MANIFEST_LOAD_FAILED")

    cocotb_dir = Path(__file__).resolve().parents[1]
    for p in (cocotb_dir, cocotb_dir / "tests"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from env import sep_payload_mutate as pm

    buf = bytearray(Path(BUILD_DIR / "oca_secure_boot.bin").read_bytes())
    assert selector_mask("package", 0) == 1 << 32 and selector_mask("chiplet", 3) == 1 << 3
    set_identity(buf, "primary", "package", bytes(32), selector_mask("package", 5))
    pm.verify_sealed(buf, "primary")
    set_lifecycle_constraint(buf, "primary", allowed=1 << 2)
    pm.verify_sealed(buf, "primary")
    from rom_fw import sep_manifest_field_defect as fd

    assert fd.assert_consumer_body_size(buf) == 4096
    lc_bit = 1 << SELECTOR_BIT_LIFECYCLE["chiplet"]
    assert (
        selector_bits(buf, "primary") == selector_mask("package", 5) | lc_bit == 1 << 37 | 1 << 96
    )
    want_package = bytes(0 if i == 5 else SHIPPED_IDENTITY_BYTE for i in range(IDENTITY_LEN))
    assert identity(buf, "primary", "package") == want_package
    assert lifecycle_states(buf, "primary", "chiplet") == 1 << 2
    assert selector_mask("system", 31) == 1 << 95
    for bad_args in (("package", 32), ("series", 0)):
        try:
            selector_mask(*bad_args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"selector_mask{bad_args} was accepted")
    try:
        set_identity(buf, "primary", "chiplet", bytes(32), selector_mask("package", 0))
    except ValueError:
        pass
    else:
        raise AssertionError("set_identity accepted a mask outside its own field")
    for level, off in (("package", 140), ("system", 144)):
        u = bytearray(Path(BUILD_DIR / "oca_secure_boot.bin").read_bytes())
        set_lifecycle_constraint(u, "primary", allowed=0x7F, level=level)
        pm.verify_sealed(u, "primary")
        assert selector_bits(u, "primary") == 1 << SELECTOR_BIT_LIFECYCLE[level]
        at = slot_base("primary") + off
        assert int.from_bytes(u[at : at + 4], "little") == 0x7F
    print(
        f"\nidentity/lifecycle setters: ok (package lifecycle bit {SELECTOR_BIT_LIFECYCLE['package']})"
    )

    img = (BUILD_DIR / "oca_identity_boot.bin").read_bytes()
    want = selector_mask("chiplet", 0) | selector_mask("chiplet", 1)
    assert selector_bits(img, "primary") == want, hex(selector_bits(img, "primary"))
    assert identity(img, "primary", "chiplet")[:2] == b"\xde\xad"
    verify_identity_layout(img, "primary")
    print(f"oca_identity_boot.bin selector 0x{want:x}: per-byte model agrees with the packer")

    enc = bytearray((BUILD_DIR / "oca_encrypted_boot.bin").read_bytes())
    set_identity(enc, "backup", "system", bytes(range(32)), selector_mask("system", 0))
    pm.verify_sealed(enc, "backup")
    print("encrypted slot: set_identity re-seals and the decrypted TOC still verifies")

    # A second field's set_identity must not flag the first field's bytes as strays.
    two = bytearray(Path(BUILD_DIR / "oca_secure_boot.bin").read_bytes())
    set_identity(two, "primary", "chiplet", bytes(32), selector_mask("chiplet", 0))
    pm.verify_sealed(two, "primary")
    set_identity(two, "primary", "package", bytes(32), selector_mask("package", 1))
    pm.verify_sealed(two, "primary")
    assert identity(two, "primary", "chiplet") == bytes(
        0 if i == 0 else SHIPPED_IDENTITY_BYTE for i in range(IDENTITY_LEN)
    )
    assert identity(two, "primary", "package") == bytes(
        0 if i == 1 else SHIPPED_IDENTITY_BYTE for i in range(IDENTITY_LEN)
    )
    verify_identity_layout(two, "primary")
    print("two successive set_identity calls: both verify_sealed, unselected bytes stay 0xA5")

    m = bytearray(buf)
    set_manifest_length(m, "primary", BODY_SIZE + 4)
    try:
        fd.assert_consumer_body_size(m)
    except AssertionError:
        pass
    else:
        raise AssertionError("assert_consumer_body_size accepted a mutated manifest_length")
    print(f"consumer body size: {fd.assert_consumer_body_size()}")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
