#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Dump a SystemRDL register space as a JSON tree.

Emits the addrmap/regfile/reg/mem/field hierarchy with the addressing and
software-access facts a testbench needs to walk registers generically. The
cocotb register_test walks this instead of a generated header so it can iterate
every register without a per-register binding.

The schema is a contract with those consumers, so SCRIPT_VERSION tracks the
schema rather than this file: it is carried in the root object and only moves
when the emitted shape changes.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Union

from systemrdl import RDLCompileError, RDLCompiler, node

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.rdlview import parse_rdl_params  # noqa: E402

SCRIPT_VERSION = "r2026-08-04"


class JsonExporter:
    def __init__(self, root, compact_arrays=False, repo_root=None, git_sha="unknown"):
        self.root = root
        self.compact_arrays = compact_arrays
        self.repo_root = repo_root
        self.git_sha = git_sha
        # Unrolled array instances are flattened into <name>_<n>, so each kind of
        # node needs its own running index.
        self.array_regs = {}
        self.array_mems = {}
        self.array_addrmaps = {}
        self.array_regfiles = {}

    def def_file(self, obj) -> str:
        path = obj.inst.def_src_ref.path if obj.inst.def_src_ref else ""
        if path and self.repo_root:
            path = str(Path(path).absolute().relative_to(self.repo_root))
        return path

    @staticmethod
    def type_name(obj) -> str:
        return obj.orig_type_name if obj.orig_type_name else obj.type_name

    @staticmethod
    def array_total(obj) -> int:
        if not obj.is_array:
            return 0
        size = 1
        for dim in obj.array_dimensions:
            size *= dim
        return size

    def indexed_name(self, obj, counters) -> str:
        """Append a running index to an unrolled array instance's name."""
        if self.compact_arrays or not obj.is_array:
            return obj.inst_name
        nxt = 0 if obj.inst_name not in counters else counters[obj.inst_name] + 1
        counters[obj.inst_name] = nxt
        return f"{obj.inst_name}_{nxt}"

    def field(self, obj: node.FieldNode) -> dict:
        out = {
            "def_file": self.def_file(obj),
            "type": "field",
            "inst_name": obj.inst_name,
            "desc": obj.get_property("desc", default=""),
            "lsb": obj.lsb,
            "msb": obj.msb,
            "reset": obj.get_property("reset"),
            "sw_access": obj.get_property("sw").name,
            "woclr": 1 if obj.get_property("woclr") else 0,
        }

        # onwrite/onread are the explicit form; woset/woclr and rset/rclr are the
        # shorthand RDL allows instead. Report whichever the source used.
        on_write = obj.get_property("onwrite", default=None)
        if on_write is None:
            woset = obj.get_property("woset")
            woclr = obj.get_property("woclr")
            if woset and woclr:
                raise RuntimeError(f"field {obj.inst_name} sets both woset and woclr")
            out["onwrite"] = "woset" if woset else ("woclr" if woclr else "")
        else:
            out["onwrite"] = on_write.name

        on_read = obj.get_property("onread", default=None)
        if on_read is None:
            rset = obj.get_property("rset")
            rclr = obj.get_property("rclr")
            if rset and rclr:
                raise RuntimeError(f"field {obj.inst_name} sets both rset and rclr")
            out["onread"] = "rset" if rset else ("rclr" if rclr else "")
        else:
            out["onread"] = on_read.name

        out["singlepulse"] = 1 if obj.get_property("singlepulse") else 0
        return out

    def reg(self, obj: node.RegNode) -> dict:
        out = {
            "def_file": self.def_file(obj),
            "type": "reg",
            "inst_name": self.indexed_name(obj, self.array_regs),
            "def_type": self.type_name(obj),
            "desc": obj.get_property("desc", default=""),
            "addr_offset": (obj.raw_address_offset if self.compact_arrays else obj.address_offset),
            "regsize": obj.get_property("regwidth"),
            "accesssize": obj.get_property("accesswidth"),
        }
        if self.compact_arrays and obj.is_array:
            out["array_size"] = self.array_total(obj)
            out["array_increment"] = obj.array_stride
        out["children"] = [self.field(f) for f in obj.fields()]
        return out

    def mem(self, obj: node.MemNode) -> dict:
        out = {
            "def_file": self.def_file(obj),
            "type": "mem",
            "inst_name": self.indexed_name(obj, self.array_mems),
            "addr_offset": (obj.raw_address_offset if self.compact_arrays else obj.address_offset),
            "def_type": self.type_name(obj),
            "desc": obj.get_property("desc", default=""),
            "memwidth": obj.get_property("memwidth"),
            "mementries": obj.get_property("mementries"),
        }
        if self.compact_arrays and obj.is_array:
            out["array_size"] = self.array_total(obj)
            out["array_increment"] = obj.array_stride
        return out

    def container(self, obj: Union[node.AddrmapNode, node.RegfileNode]) -> dict:
        if isinstance(obj, node.AddrmapNode):
            kind, counters = "addrmap", self.array_addrmaps
        elif isinstance(obj, node.RegfileNode):
            kind, counters = "regfile", self.array_regfiles
        else:
            raise RuntimeError(f"unexpected container node: {obj}")

        inst_name = self.indexed_name(obj, counters)

        out = {}
        # Provenance belongs to the model as a whole, so it rides on the root only.
        if obj == self.root.top:
            out["script_version"] = SCRIPT_VERSION
            out["git_sha"] = self.git_sha
        out["def_file"] = self.def_file(obj)
        out["type"] = kind
        out["inst_name"] = inst_name
        out["def_type"] = self.type_name(obj)
        out["addr_offset"] = obj.raw_address_offset if self.compact_arrays else obj.address_offset
        # Declared extent of one array element, which can exceed what the children
        # occupy when the RDL pads a map out to a fixed aperture.
        out["size"] = obj.size
        if self.compact_arrays and obj.is_array:
            out["array_size"] = self.array_total(obj)
            out["array_increment"] = obj.array_stride
        out["desc"] = obj.get_property("desc") or ""

        children = []
        for child in obj.children(unroll=(not self.compact_arrays)):
            if isinstance(child, (node.AddrmapNode, node.RegfileNode)):
                children.append(self.container(child))
            elif isinstance(child, node.RegNode):
                children.append(self.reg(child))
            elif isinstance(child, node.MemNode):
                children.append(self.mem(child))
        out["children"] = children
        return out

    def write(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.container(self.root.top), f, indent=4)


def zero_symbolic_resets(inst):
    """Force non-integer resets to 0.

    A reset can elaborate to a reference (another field, a parameter) rather than
    a literal. json.dump cannot serialise that, and no consumer of this model
    reads reset values symbolically, so collapse them.
    """
    if isinstance(inst, str):
        return inst
    if "reset" in inst.properties and not isinstance(inst.properties["reset"], int):
        inst.properties["reset"] = 0
    for i, child in enumerate(inst.children):
        inst.children[i] = zero_symbolic_resets(child)
    return inst


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_rdl_file")
    parser.add_argument("output_json_file")
    parser.add_argument(
        "-u", "--udp_rdl_file", required=True, help="the PeakRDL UDP RDL file (./regblock_udps.rdl)"
    )
    parser.add_argument("-t", "--top", help="address map to use as the top")
    parser.add_argument(
        "-i", "--incdir", action="append", help="directory to search for included files"
    )
    parser.add_argument(
        "-c",
        "--compact_arrays",
        action="store_true",
        help="emit arrays as a size/stride pair instead of unrolling",
    )
    parser.add_argument(
        "-r", "--repo-root", help="root the def_file paths are reported relative to"
    )
    parser.add_argument(
        "-g",
        "--git_sha",
        default=os.getenv("GIT_SHA", "unknown"),
        help="git SHA recorded in the model",
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

    root.inst = zero_symbolic_resets(root.inst)
    for name in root.inst.comp_defs:
        root.inst.comp_defs[name] = zero_symbolic_resets(root.inst.comp_defs[name])

    JsonExporter(
        root,
        compact_arrays=args.compact_arrays,
        repo_root=Path(args.repo_root).absolute() if args.repo_root else None,
        git_sha=args.git_sha,
    ).write(args.output_json_file)


if __name__ == "__main__":
    main()
