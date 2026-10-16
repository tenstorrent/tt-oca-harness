# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Shared RDL walk and field layout helpers for flattened register headers.

Used by `rdlsvh.py` and `rdlpyhdr.py` so both emitters see the same
per-register field list, reserved gaps, and reset defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from systemrdl import RDLListener
from systemrdl.node import FieldNode, SignalNode
from systemrdl.rdltypes import PropertyReference, UserEnum

from .fieldprops import extract_field_props


@dataclass
class FieldInfo:
    name: str
    high: int
    low: int
    reset: int | None  # None when the field has no constant reset value
    sw: str
    hw: str
    onwrite: str
    onread: str
    singlepulse: bool
    volatile: bool


@dataclass
class RegTypeInfo:
    address: int
    regwidth: int
    path: str  # instance whose fields are recorded, named when another disagrees
    fields: list = field(default_factory=list)  # FieldInfo, low-to-high


@dataclass
class RegInstInfo:
    dims: object  # array dimensions, or None for a scalar
    regwidth: int
    type_name: str
    address: int


# Field identity and access properties every instance of a type must agree on;
# reset may differ per instance.
FIELD_ACCESS_PROPS = (
    "name",
    "high",
    "low",
    "sw",
    "hw",
    "onwrite",
    "onread",
    "singlepulse",
    "volatile",
)


def check_same_fields(type_name: str, known: RegTypeInfo, path: str, fields: list) -> None:
    """Raise when instance `path` of `type_name` disagrees with the one in `known`."""
    where = f"register type '{type_name}' ({known.path} vs {path})"
    if len(known.fields) != len(fields):
        raise ValueError(f"{where}: {len(known.fields)} fields vs {len(fields)}")
    for old, new in zip(known.fields, fields):
        for prop in FIELD_ACCESS_PROPS:
            if getattr(old, prop) != getattr(new, prop):
                raise ValueError(
                    f"{where}: field '{old.name}' {prop} {getattr(old, prop)!r} "
                    f"vs {getattr(new, prop)!r}"
                )


def constant_reset(node, reset) -> int | None:
    """Integer reset of a field, or None when a signal, field or property drives it."""
    if reset is None or isinstance(reset, (SignalNode, FieldNode, PropertyReference)):
        return None
    if isinstance(reset, UserEnum):
        return reset.value
    if isinstance(reset, int):
        return reset
    raise ValueError(f"field '{node.get_path()}' has an unsupported reset {reset!r}")


def reg_type_name(node) -> str:
    """Flattened register type name: the parent's type, then the register's."""
    # Prefer orig_type_name; type_name may carry a hash when properties are dynamic.
    fullname = node.parent.type_name.removesuffix("_ispresent_t").upper()
    if node.orig_type_name is None:
        return fullname + "_" + node.type_name
    return fullname + "_" + node.orig_type_name.upper()


def path_minus_root(node) -> str:
    elems = node.get_path(array_suffix="_{index:d}_").split(".")[1:]
    return "_".join(elems)


def def_name(node, shorten_names: bool) -> str:
    if shorten_names:
        return node.get_path_segment(array_suffix="_{index:d}_").upper()
    return path_minus_root(node).upper()


class FieldCollector(RDLListener):
    """Collect per-type field layouts and per-instance shapes under a target addrmap.

    Subclasses may override enter_* methods for text emission; call super() first
    so collection stays consistent.
    """

    def __init__(self, root, target_addr_map, shorten_names):
        self.root = root
        self.target_addr_map = target_addr_map
        self.shorten_names = shorten_names

        self.under_target = False
        self.regs: dict[str, RegTypeInfo] = {}
        self.reg_inst_count: dict[str, RegInstInfo] = {}
        self.curr_reg_fields: list[FieldInfo] = []
        self.curr_reg_inst: RegInstInfo | None = None  # set by exit_Reg for subclasses

    def path_minus_root(self, node) -> str:
        return path_minus_root(node)

    def def_name(self, node) -> str:
        return def_name(node, self.shorten_names)

    def enter_Addrmap(self, node):
        name = node.get_path_segment()
        if node.parent == self.root and self.target_addr_map is None:
            self.target_addr_map = name
        if name == self.target_addr_map:
            self.under_target = True

    def exit_Addrmap(self, node):
        if node.get_path_segment() == self.target_addr_map:
            self.under_target = False
            self.reg_inst_count = dict(
                sorted(self.reg_inst_count.items(), key=lambda item: item[1].address)
            )

    def enter_Reg(self, node):
        if self.under_target:
            self.curr_reg_fields = []

    def exit_Reg(self, node):
        if not self.under_target:
            return
        parent = node.parent
        fullname = reg_type_name(node)

        # Nested under a non-target parent: prefix to avoid instance-name collisions.
        if parent.get_path_segment().lower() == self.target_addr_map.lower():
            inst_name = node.get_path_segment(array_suffix="").upper()
        else:
            inst_name = (
                parent.get_path_segment(array_suffix="_{index:d}_").upper()
                + "_"
                + node.get_path_segment(array_suffix="").upper()
            )

        first_in_array = node.is_array and all(i == 0 for i in node.current_idx)
        if not node.is_array or first_in_array:
            self.reg_inst_count[inst_name] = RegInstInfo(
                dims=node.array_dimensions if node.is_array else None,
                regwidth=node.get_property("regwidth"),
                type_name=fullname,
                address=node.absolute_address,
            )

        fields = sorted(self.curr_reg_fields, key=lambda f: f.low)
        path = node.get_path()
        if fullname in self.regs:
            check_same_fields(fullname, self.regs[fullname], path, fields)

        self.regs[fullname] = RegTypeInfo(
            address=node.raw_absolute_address,
            regwidth=node.get_property("regwidth"),
            path=path,
            fields=fields,
        )
        self.curr_reg_inst = self.reg_inst_count[inst_name]

    def enter_Field(self, node):
        if self.under_target:
            props = extract_field_props(node)
            self.curr_reg_fields.append(
                FieldInfo(
                    name=node.get_path_segment(array_suffix="_{index:d}_"),
                    high=node.high,
                    low=node.low,
                    reset=constant_reset(node, props.reset),
                    sw=props.sw,
                    hw=props.hw,
                    onwrite=props.onwrite,
                    onread=props.onread,
                    singlepulse=props.singlepulse,
                    volatile=props.volatile,
                )
            )


def build_struct_fields(fields: list[FieldInfo]) -> list[tuple[str, int]]:
    """Fill bit gaps with `rsvd_N`. Returns `(name, width)` in LSB-first order."""
    struct_fields: list[tuple[str, int]] = []
    bit_idx = 0
    rsvd_count = 0
    for f in fields:
        if bit_idx < f.low:
            struct_fields.append((f"rsvd_{rsvd_count}", f.low - bit_idx))
            bit_idx = f.low
            rsvd_count += 1
        struct_fields.append((f.name.lower(), f.high - f.low + 1))
        bit_idx = f.high + 1
    return struct_fields


def compute_default(fields: list[FieldInfo]) -> int:
    """OR constant field resets into a register default; fields without one contribute 0."""
    reg_reset = 0
    for f in fields:
        reg_reset |= (f.reset or 0) << f.low
    return reg_reset
