# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Shared RDL walk and field layout helpers for flattened register headers.

Used by `rdlsvh.py` and `rdlpyhdr.py` so both emitters see the same
per-register field list, reserved gaps, and reset defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from systemrdl import RDLListener
from systemrdl.node import SignalNode


@dataclass
class FieldInfo:
    name: str
    high: int
    low: int
    reset: object  # int, or SignalNode when reset is hardware-driven
    sw: str
    onwrite: str
    onread: str
    singlepulse: bool


@dataclass
class RegTypeInfo:
    address: int
    regwidth: int
    fields: list = field(default_factory=list)  # FieldInfo, low-to-high


@dataclass
class RegInstInfo:
    dims: object  # array dimensions, or None for a scalar
    regwidth: int
    type_name: str
    address: int


def field_access_key(field_info: FieldInfo) -> tuple:
    """Field identity and software-visible access properties, excluding reset."""
    return (
        field_info.name,
        field_info.high,
        field_info.low,
        field_info.sw,
        field_info.onwrite,
        field_info.onread,
        field_info.singlepulse,
    )


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

        # Prefer orig_type_name; type_name may carry a hash when properties are dynamic.
        fullname = parent.type_name.removesuffix("_ispresent_t").upper()
        if node.orig_type_name is None:
            fullname += "_" + node.type_name
        else:
            fullname += "_" + node.orig_type_name.upper()

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

        # Same type must agree on field layout and access (reset may differ).
        if fullname in self.regs:
            existing_fields = self.regs[fullname].fields
            if [field_access_key(f) for f in existing_fields] != [
                field_access_key(f) for f in fields
            ]:
                raise ValueError(f"ERROR: register '{fullname}' already exists")

        self.regs[fullname] = RegTypeInfo(
            address=node.raw_absolute_address,
            regwidth=node.get_property("regwidth"),
            fields=fields,
        )

    def enter_Field(self, node):
        if self.under_target:
            reset = node.get_property("reset")
            onwrite = node.get_property("onwrite", default=None)
            if onwrite is None:
                onwrite = (
                    "woset"
                    if node.get_property("woset")
                    else ("woclr" if node.get_property("woclr") else "")
                )
            else:
                onwrite = onwrite.name
            onread = node.get_property("onread", default=None)
            if onread is None:
                onread = (
                    "rset"
                    if node.get_property("rset")
                    else ("rclr" if node.get_property("rclr") else "")
                )
            else:
                onread = onread.name
            self.curr_reg_fields.append(
                FieldInfo(
                    name=node.get_path_segment(array_suffix="_{index:d}_"),
                    high=node.high,
                    low=node.low,
                    reset=0 if reset is None else reset,
                    sw=node.get_property("sw").name,
                    onwrite=onwrite,
                    onread=onread,
                    singlepulse=bool(node.get_property("singlepulse")),
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
    """OR constant field resets into a register default; SignalNode resets contribute 0."""
    reg_reset = 0
    for f in fields:
        reset = 0 if isinstance(f.reset, SignalNode) else f.reset
        reg_reset |= reset << f.low
    return reg_reset
