# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Declarative mutations of an OCA SEP boot image.

A byte patch edits a packed image and leaves its integrity fields stale, so it exercises
the ROM integrity checks.
An op runs a whitelisted DV helper that keeps the manifest hash consistent.
A repack edits the packer inputs and rebuilds, so hashes and signatures cover the change.
A byte patch may follow an op or repack to break one integrity field.
"""

import os
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import oca_layout as L
from sepvp import paths


def testlist_dir() -> Path:
    """The testlist root; env SEPVP_TESTLIST_DIR selects an alternate one."""
    return Path(os.environ.get("SEPVP_TESTLIST_DIR", Path(__file__).parent / "testlist"))


def spec_dir() -> Path:
    return testlist_dir() / "boot_image_mutations"


_SPEC_FIELDS = {"base", "patch", "pack_config", "set", "pin", "ops"}
_EDIT_FIELDS = {"target", "slot", "path", "value"}
_OP_FIELDS = {"op", "slot", "args"}
_SLOTS = {"primary": L.PRIMARY_OFFSET, "backup": L.BACKUP_OFFSET}
_EDIT_SLOTS = ("primary", "backup", "both")
_TARGETS = ("image", "bundle")
_COMBO_CONFIG = re.compile(r"combos\.\d+\.config")
_PACK_CONFIG = re.compile(r"oca_[A-Za-z0-9_]+")


@dataclass(frozen=True)
class Fill:
    """Blank a half-open span; ``high=None`` runs to the end of the image."""

    low: int
    high: int | None
    value: int


@dataclass(frozen=True)
class SetByte:
    offset: int
    value: int


@dataclass(frozen=True)
class XorByte:
    offset: int
    value: int


@dataclass(frozen=True)
class SetInt:
    """Write a little-endian integer field at the width the manifest declares."""

    offset: int
    value: int
    size: int


Patch = Fill | SetByte | XorByte | SetInt
_INT_SIZES = (1, 2, 4, 8)


@dataclass(frozen=True)
class FieldPatch:
    """A byte patch addressed by OCA manifest field name within one slot."""

    field: str
    slot: str
    inner: SetByte | XorByte | SetInt

    def resolve(self) -> SetByte | XorByte | SetInt:
        offset = _SLOTS[self.slot] + getattr(L.C, self.field) + self.inner.offset
        if isinstance(self.inner, SetInt):
            return SetInt(offset, self.inner.value, self.inner.size)
        return type(self.inner)(offset, self.inner.value)


@dataclass(frozen=True)
class PackEdit:
    """One packer-input edit or pin: ``image`` is the combined config, ``bundle`` a slot's."""

    target: str
    slot: str | None
    path: str
    value: int | str


@dataclass(frozen=True)
class OcaOp:
    """One whitelisted DV mutation helper applied to one slot of a packed image."""

    op: str
    slot: str
    args: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BootImageMutation:
    name: str
    base: str | None
    patch: tuple[Patch, ...]
    pack_config: str | None = None
    set: tuple[PackEdit, ...] = ()
    pin: tuple[PackEdit, ...] = ()
    ops: tuple[OcaOp, ...] = ()


def _byte(value: object, name: str, what: str) -> int:
    if type(value) is not int or not 0 <= value <= 0xFF:
        raise ValueError(f"mutation {name!r} {what} value must be a byte")
    return value


def _fill(entry: dict, name: str) -> Fill:
    bounds = entry["fill"]
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError(f"mutation {name!r} fill must be a [low, high] range")
    low, high = bounds
    if type(low) is not int or low < 0:
        raise ValueError(f"mutation {name!r} fill low bound must be a non-negative integer")
    if high != "end" and type(high) is not int:
        raise ValueError(f"mutation {name!r} fill high bound must be an integer or 'end'")
    if high != "end" and low >= high:
        raise ValueError(f"mutation {name!r} fill range is empty")
    if "value" not in entry:
        raise ValueError(f"mutation {name!r} fill needs a value")
    return Fill(low, None if high == "end" else high, _byte(entry["value"], name, "fill"))


def _byte_patch(entry: dict, name: str, offset: int) -> SetByte | XorByte | SetInt:
    if "value" in entry:
        return SetByte(offset, _byte(entry["value"], name, "offset"))
    if "xor" in entry:
        return XorByte(offset, _byte(entry["xor"], name, "xor"))
    if "le" in entry:
        value = entry["le"]
        if type(value) is not int or value < 0:
            raise ValueError(f"mutation {name!r} le must be a non-negative integer")
        if "size" not in entry:
            raise ValueError(f"mutation {name!r} le needs a size, the field's width")
        size = entry["size"]
        if size not in _INT_SIZES:
            raise ValueError(f"mutation {name!r} size must be one of {list(_INT_SIZES)}")
        return SetInt(offset, value, size)
    raise ValueError(f"mutation {name!r} byte patch needs value, xor or le")


def _field_patch(entry: dict, name: str) -> FieldPatch:
    field_name = entry["field"]
    if not isinstance(field_name, str) or not field_name.startswith("OFF_"):
        raise ValueError(f"mutation {name!r} field must name an OFF_ manifest constant")
    if field_name.startswith("OFF_TOC_"):
        raise ValueError(
            f"mutation {name!r} field {field_name} is an OFF_TOC_ offset, relative to the "
            "TOC rather than the manifest; use an op or an absolute offset"
        )
    if type(getattr(L.C, field_name, None)) is not int:
        raise ValueError(f"mutation {name!r} field {field_name}: no OCA field of that name")
    slot = entry.get("slot")
    if slot not in _SLOTS:
        raise ValueError(f"mutation {name!r} field patch needs slot primary or backup")
    return FieldPatch(field_name, slot, _byte_patch(entry, name, 0))


def _parse_patch(entry: object, name: str) -> Patch:
    if not isinstance(entry, dict):
        raise ValueError(f"mutation {name!r} each patch must be a table")
    if sum(key in entry for key in ("fill", "offset", "field")) != 1:
        raise ValueError(f"mutation {name!r} patch must name exactly one of fill, offset, field")
    if "field" in entry:
        return _field_patch(entry, name).resolve()
    if "slot" in entry:
        raise ValueError(f"mutation {name!r} slot applies only to a field patch")
    if "fill" in entry:
        return _fill(entry, name)
    offset = entry["offset"]
    if type(offset) is not int or offset < 0:
        raise ValueError(f"mutation {name!r} offset must be a non-negative integer")
    return _byte_patch(entry, name, offset)


def _parse_edit(entry: object, name: str, kind: str) -> PackEdit:
    if not isinstance(entry, dict):
        raise ValueError(f"mutation {name!r} each {kind} entry must be a table")
    unknown = set(entry) - _EDIT_FIELDS
    if unknown:
        raise ValueError(f"mutation {name!r} {kind} entry has unknown field {sorted(unknown)[0]!r}")
    target = entry.get("target")
    if target not in _TARGETS:
        raise ValueError(f"mutation {name!r} {kind} target must be one of {list(_TARGETS)}")
    slot = entry.get("slot")
    if target == "bundle" and slot not in _EDIT_SLOTS:
        raise ValueError(f"mutation {name!r} bundle {kind} needs slot in {list(_EDIT_SLOTS)}")
    if target == "image" and slot is not None:
        raise ValueError(f"mutation {name!r} image {kind} takes no slot; it edits both combos")
    path = entry.get("path")
    if not isinstance(path, str) or not path or any(not step for step in path.split(".")):
        raise ValueError(f"mutation {name!r} {kind} path must be a non-empty dotted string")
    if target == "image" and _COMBO_CONFIG.fullmatch(path):
        raise ValueError(
            f"mutation {name!r} {kind} path {path}: the repack owns combos.<n>.config; "
            "edit the slot's bundle instead"
        )
    if "value" not in entry:
        raise ValueError(f"mutation {name!r} {kind} entry needs a value")
    value = entry["value"]
    if type(value) not in (int, str):
        raise ValueError(f"mutation {name!r} {kind} value must be an integer or a string")
    return PackEdit(target, slot, path, value)


def _edit_keys(edit: PackEdit) -> list[tuple[str, str | None, str]]:
    slots = ("primary", "backup") if edit.slot == "both" else (edit.slot,)
    return [(edit.target, slot, edit.path) for slot in slots]


def _parse_op(entry: object, name: str) -> OcaOp:
    if not isinstance(entry, dict):
        raise ValueError(f"mutation {name!r} each ops entry must be a table")
    unknown = set(entry) - _OP_FIELDS
    if unknown:
        raise ValueError(f"mutation {name!r} ops entry has unknown field {sorted(unknown)[0]!r}")
    op = entry.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError(f"mutation {name!r} ops entry needs a non-empty op name")
    slot = entry.get("slot")
    if slot not in _SLOTS:
        raise ValueError(f"mutation {name!r} op {op} needs slot primary or backup")
    args = entry.get("args", {})
    if not isinstance(args, dict):
        raise ValueError(f"mutation {name!r} op {op} args must be a table")
    return OcaOp(op, slot, dict(args))


def _array(data: dict, key: str, name: str) -> list:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"mutation {name!r} {key} must be an array")
    return value


def _parse_repack(name: str, data: dict, patches: tuple[Patch, ...]) -> BootImageMutation:
    pack_config = data["pack_config"]
    if not isinstance(pack_config, str) or not _PACK_CONFIG.fullmatch(pack_config):
        raise ValueError(
            f"mutation {name!r} pack_config must be an oca_<name> config stem, "
            f"without a directory or extension, got {pack_config!r}"
        )
    if not (paths.BOOTCODE_CONFIGS / f"{pack_config}_image.yaml").is_file():
        raise ValueError(
            f"mutation {name!r} pack_config {pack_config}: no packer config "
            f"{pack_config}_image.yaml in {paths.BOOTCODE_CONFIGS}"
        )
    edits = tuple(_parse_edit(entry, name, "set") for entry in _array(data, "set", name))
    pins = tuple(_parse_edit(entry, name, "pin") for entry in _array(data, "pin", name))
    if not edits:
        raise ValueError(f"mutation {name!r} repack must declare at least one set entry")
    keys = [key for edit in (*edits, *pins) for key in _edit_keys(edit)]
    if len(set(keys)) != len(keys):
        raise ValueError(
            f"mutation {name!r} names one packer field twice across set and pin, so the "
            "spec does not say which value the testcase is about"
        )
    return BootImageMutation(
        name=name, base=None, patch=patches, pack_config=pack_config, set=edits, pin=pins
    )


def _parse_mutation(name: str, data: dict) -> BootImageMutation:
    unknown = set(data) - _SPEC_FIELDS
    if unknown:
        raise ValueError(f"mutation {name!r} has unknown field {sorted(unknown)[0]!r}")
    if not data:
        raise ValueError(
            f"mutation {name!r} must be a byte patch (base + patch), an op spec "
            "(base + ops) or a repack (pack_config + set)"
        )
    patches = tuple(_parse_patch(entry, name) for entry in _array(data, "patch", name))

    if "pack_config" in data:
        clash = sorted({"base", "ops"} & set(data))
        if clash:
            raise ValueError(
                f"mutation {name!r} names both pack_config and {clash[0]}; a repack builds "
                "its own bytes from the packer config"
            )
        return _parse_repack(name, data, patches)

    for key in ("set", "pin"):
        if key in data:
            raise ValueError(f"mutation {name!r} {key} applies only to a pack_config repack")
    base = data.get("base")
    if not isinstance(base, str) or not base.strip():
        raise ValueError(f"mutation {name!r} needs a base image name")

    if "ops" in data:
        ops = tuple(_parse_op(entry, name) for entry in _array(data, "ops", name))
        if not ops:
            raise ValueError(f"mutation {name!r} ops must declare at least one op")
        return BootImageMutation(name=name, base=base, patch=patches, ops=ops)

    if not patches:
        raise ValueError(f"mutation {name!r} must declare at least one patch")
    return BootImageMutation(name=name, base=base, patch=patches)


def load_mutations(directory: str | Path | None = None) -> Mapping[str, BootImageMutation]:
    """Load every mutation spec in *directory* (default: spec_dir()), keyed by its file stem."""
    mutations = {}
    for path in sorted(Path(directory or spec_dir()).glob("*.toml")):
        with path.open("rb") as spec_file:
            mutations[path.stem] = _parse_mutation(path.stem, tomllib.load(spec_file))
    return mutations


def apply_patches(data: bytes, patches: Sequence[Patch]) -> bytes:
    """Return *data* with every patch applied, rejecting any that changes nothing."""
    out = bytearray(data)
    for patch in patches:
        if isinstance(patch, Fill):
            high = len(out) if patch.high is None else patch.high
            if not 0 <= patch.low < high <= len(out):
                raise ValueError(
                    f"fill [0x{patch.low:x},0x{high:x}) is out of bounds for a "
                    f"0x{len(out):x}-byte image"
                )
            replacement = bytes([patch.value]) * (high - patch.low)
            if out[patch.low : high] == replacement:
                # A no-op mutation would leave the testcase passing without exercising its fault.
                raise ValueError(
                    f"fill [0x{patch.low:x},0x{high:x}) is already all "
                    f"0x{patch.value:02x}, so the mutation is a no-op"
                )
            out[patch.low : high] = replacement
            continue

        if isinstance(patch, SetInt):
            try:
                replacement = patch.value.to_bytes(patch.size, "little")
            except OverflowError:
                raise ValueError(f"0x{patch.value:x} does not fit in {patch.size} bytes") from None
            if not (0 <= patch.offset and patch.offset + patch.size <= len(out)):
                raise ValueError(
                    f"field [0x{patch.offset:x},0x{patch.offset + patch.size:x}) is "
                    f"out of bounds for a 0x{len(out):x}-byte image"
                )
            if out[patch.offset : patch.offset + patch.size] == replacement:
                raise ValueError(
                    f"field at 0x{patch.offset:x} already holds 0x{patch.value:x}, "
                    "so the mutation is a no-op"
                )
            out[patch.offset : patch.offset + patch.size] = replacement
            continue

        if not 0 <= patch.offset < len(out):
            raise ValueError(
                f"patch offset 0x{patch.offset:x} is out of bounds for a 0x{len(out):x}-byte image"
            )
        updated = patch.value if isinstance(patch, SetByte) else out[patch.offset] ^ patch.value
        if updated == out[patch.offset]:
            raise ValueError(
                f"patch at 0x{patch.offset:x} leaves the byte at "
                f"0x{updated:02x}, so the mutation is a no-op"
            )
        out[patch.offset] = updated
    return bytes(out)
