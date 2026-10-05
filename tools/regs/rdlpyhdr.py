#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate a flat Python register header from a SystemRDL register space.

Emits address/offset constants, reset values, field-access metadata, and optional
`ctypes.Structure`/`Union` bitfield classes with `rsvd_N` gaps.

Registers wider than 64 bits, or blocks with `--bitfields none`, get constants
only (no ctypes classes).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from systemrdl import RDLCompileError, RDLCompiler, RDLWalker
from systemrdl.node import AddressableNode, MemNode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.rdlview import parse_rdl_params  # noqa: E402
from common.regcollect import FieldCollector, build_struct_fields, compute_default  # noqa: E402

SCRIPT_VERSION = "r2026-08-30"

CTYPE_BY_WIDTH = {8: "c_uint8", 16: "c_uint16", 32: "c_uint32", 64: "c_uint64"}


def base_ctype_for_width(total_bits: int) -> str | None:
    for width in (8, 16, 32, 64):
        if total_bits <= width:
            return CTYPE_BY_WIDTH[width]
    return None


class PyListener(FieldCollector):
    def __init__(self, root, args):
        super().__init__(root, args.addrmap, args.shorten_names)
        self.addr_width = int(args.addr_width)
        self.addr_lines: list[str] = []

    def const(self, name, value, width_bits=None):
        digits = -((width_bits or self.addr_width) // -4)
        return f"{name} = 0x{value:0{digits}X}"

    def enter_Addrmap(self, node):
        super().enter_Addrmap(node)
        if not self.under_target:
            return
        name = node.get_path_segment()
        if self.shorten_names or node.parent == self.root:
            def_name = (
                node.get_path_segment(array_suffix="_{index:d}_").upper()
                if self.shorten_names
                else name.upper()
            )
        else:
            def_name = self.def_name(node)

        if node.parent == self.root:
            # Top-level addrmap base is 0 in the spec; use the lowest child address.
            base = min(
                (
                    c.absolute_address
                    for c in node.children(unroll=True)
                    if isinstance(c, AddressableNode)
                ),
                default=0,
            )
            size = node.size - base
        else:
            base = node.absolute_address
            size = node.size

        self.addr_lines.append(self.const(def_name + "_REG_MAP_BASE_ADDR", base))
        self.addr_lines.append(self.const(def_name + "_REG_MAP_SIZE", size))

    def enter_Regfile(self, node):
        if self.under_target:
            self.addr_lines.append(
                self.const(self.def_name(node) + "_REG_FILE_BASE_ADDR", node.absolute_address)
            )
            self.addr_lines.append(self.const(self.def_name(node) + "_REG_FILE_SIZE", node.size))

    def enter_Mem(self, node):
        if self.under_target:
            self.addr_lines.append(
                self.const(self.def_name(node) + "_MEM_BASE_ADDR", node.absolute_address)
            )
            self.addr_lines.append(self.const(self.def_name(node) + "_MEM_SIZE", node.size))

    def enter_Reg(self, node):
        super().enter_Reg(node)
        if not self.under_target:
            return
        if self.shorten_names:
            fullname = (
                node.parent.get_path_segment(array_suffix="_{index:d}_").upper()
                + "_"
                + node.get_path_segment(array_suffix="_{index:d}_")
            )
        else:
            fullname = self.path_minus_root(node).upper()

        # Skip address constants for registers inside a memory array.
        if not (node.is_array and isinstance(node.parent, MemNode)):
            self.addr_lines.append(self.const(fullname + "_REG_OFFSET", node.address_offset))
            self.addr_lines.append(self.const(fullname + "_REG_ADDR", node.absolute_address))


def render_registers(
    regs: dict, bitfields_enabled: bool, field_access_enabled: bool
) -> tuple[str, set[str]]:
    """Emit defaults and optional ctypes classes; return text and used ctypes names."""
    lines: list[str] = []
    used_ctypes: set[str] = set()

    for reg_name, reg in regs.items():
        if reg.regwidth > 64:
            continue

        default = compute_default(reg.fields)
        digits = -(reg.regwidth // -4)
        default_line = f"{reg_name}_REG_DEFAULT = 0x{default:0{digits}X}"
        lines.append(default_line)
        if field_access_enabled:
            lines.append(f"{reg_name}_REG_FIELD_ACCESS = (")
            lines.extend(
                "    "
                + repr(
                    (
                        field.name,
                        field.sw,
                        field.onwrite,
                        field.onread,
                        field.singlepulse,
                    )
                )
                + ","
                for field in reg.fields
            )
            lines.extend((")", ""))

        if not bitfields_enabled:
            continue

        struct_fields = build_struct_fields(reg.fields)
        total_bits = sum(width for _, width in struct_fields)
        # The bitfield storage unit only has to hold the fields, but `val` is the
        # whole register: a 32-bit register whose fields stop at bit 7 still has to
        # read and write four bytes, so the two widths are computed separately.
        ctype = base_ctype_for_width(total_bits)
        val_ctype = base_ctype_for_width(reg.regwidth)
        if ctype is None or val_ctype is None:
            continue

        used_ctypes.update({"Structure", "Union", ctype, val_ctype, "c_uint32"})

        lines += [
            f"class {reg_name}_reg_t(Structure):",
            "    _fields_ = [",
            *[f"        ('{name}', {ctype}, {width})," for name, width in struct_fields],
            "    ]",
            "",
            default_line,
            "",
            f"class {reg_name}_reg_u(Union):",
            "    _fields_ = [",
            f"        ('val', {val_ctype}),",
            f"        ('f', {reg_name}_reg_t),",
            "    ]",
            "",
            "    def __init__(self, *args, **kwargs):",
            f"        super({reg_name}_reg_u, self).__init__(*args, **kwargs)",
            f"        self.val = {reg_name}_REG_DEFAULT",
            "",
            "    def as_bytes(self):",
            "        size = 4 if isinstance(self.val, c_uint32) else 8",
            "        return self.val.to_bytes(size, 'little')",
            "",
            "    @classmethod",
            "    def from_bytes(cls, byte_seq):",
            "        instance = cls()",
            "        instance.val = int.from_bytes(byte_seq, 'little')",
            "        return instance",
            "",
        ]

    return "\n".join(lines), used_ctypes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_rdl_file")
    parser.add_argument("output_py_file")
    parser.add_argument(
        "-u", "--udp_rdl_file", required=True, help="PeakRDL UDP RDL file (./regblock_udps.rdl)"
    )
    parser.add_argument("-t", "--top", help="address map to use as the top")
    parser.add_argument(
        "-a", "--addrmap", help="address map (instance name) for which to generate output"
    )
    parser.add_argument(
        "-i", "--incdir", action="append", help="directory to search for included files"
    )
    parser.add_argument(
        "-s", "--shorten_names", action="store_true", help="use shorter constant names"
    )
    parser.add_argument("--addr_width", default=32, help="width of address bus")
    parser.add_argument(
        "--bitfields",
        choices=["none", "ltoh"],
        default="ltoh",
        help="emit ctypes classes (ltoh) or only constants (none)",
    )
    parser.add_argument(
        "--field-access",
        action="store_true",
        help="emit per-field software access and side-effect metadata",
    )
    parser.add_argument(
        "-P",
        dest="rdl_params",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override an addrmap parameter (repeatable)",
    )
    args = parser.parse_args()

    rdlc = RDLCompiler()
    try:
        rdlc.compile_file(args.udp_rdl_file)
        rdlc.compile_file(args.input_rdl_file, incl_search_paths=args.incdir)
        root = rdlc.elaborate(args.top, parameters=parse_rdl_params(args.rdl_params) or None)
    except RDLCompileError:
        sys.exit(1)

    listener = PyListener(root, args)
    RDLWalker(unroll=True).walk(root, listener)

    reg_text, used_ctypes = render_registers(
        listener.regs,
        args.bitfields != "none",
        args.field_access,
    )

    lines = [
        "# SPDX-License-Identifier: Apache-2.0",
        "# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        "# Auto-generated register header - do not edit by hand.",
        f"# Generated by {os.path.basename(sys.argv[0])} ({SCRIPT_VERSION}) "
        f"from {os.path.basename(args.input_rdl_file)}.",
    ]
    if args.field_access:
        lines.append("# *_REG_FIELD_ACCESS entries are: field, sw, onwrite, onread, singlepulse.")
    lines.append("")
    if used_ctypes:
        lines.append(f"from ctypes import {', '.join(sorted(used_ctypes))}")
        lines.append("")
    lines.extend(listener.addr_lines)
    if reg_text:
        lines.append(reg_text)

    out_path = Path(args.output_py_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
