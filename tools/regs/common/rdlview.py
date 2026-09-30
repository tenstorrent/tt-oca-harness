# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable

from systemrdl import RDLCompiler, RDLListener, RDLWalker
from systemrdl.node import AddrmapNode, FieldNode, RegNode, RootNode, SignalNode

from .fieldprops import extract_field_props


@dataclass
class Field:
    bits: str
    name: str
    access: str
    reset: str
    desc: str


@dataclass
class Reg:
    name: str
    addr: str
    access: str
    desc: str
    path: str
    fields: list[Field]


def parse_rdl_params(raw: Iterable[str] | None) -> dict[str, int]:
    """Parse PeakRDL-style NAME=VALUE addrmap parameter overrides."""
    params: dict[str, int] = {}
    for item in raw or []:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise ValueError(f"RDL parameter {item!r} is not NAME=VALUE")
        params[name] = int(value, 0)
    return params


def load_doc_overrides(rdl: str) -> dict[str, str]:
    path = Path(rdl).with_name("regdoc.toml")
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if data.get("version") != 1:
        raise ValueError(f"{path}: expected version = 1")
    registers = data.get("registers", {})
    if not isinstance(registers, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in registers.items()
    ):
        raise ValueError(f"{path}: [registers] must map selectors to descriptions")
    return registers


def compile_root(
    rdl: str,
    udp: str | None,
    incdirs: Iterable[str] | None,
    top: str | None = None,
    parameters: dict[str, int] | None = None,
    defines: dict[str, str] | None = None,
):
    c = RDLCompiler()
    if udp:
        c.compile_file(udp)
    c.compile_file(rdl, incl_search_paths=list(incdirs or []), defines=defines or {})
    kwargs: dict = {}
    if parameters:
        kwargs["parameters"] = parameters
    return c.elaborate(top, **kwargs) if top else c.elaborate(**kwargs)


def first_addrmap_name(root) -> str:
    children = list(root.children())
    if not children:
        return getattr(root, "inst_name", None) or getattr(root, "type_name", None) or "registers"
    node = children[0]
    return (
        getattr(node, "type_name", None)
        or getattr(node, "inst_name", None)
        or node.get_path_segment()
    )


def addrmap_heading(root) -> str:
    """The per-block page heading.

    Renders the addrmap's authored ``name`` (e.g. "UART 16550 Main Write-Only
    Address Map") so the reader sees the friendly title rather than the instance
    identifier. Falls back to ``Address Map: <ident>`` when no ``name`` is
    authored -- systemrdl defaults ``name`` to the instance name. The identifier
    is still carried in the section anchor and the HTML ``<h2>`` id, which the
    block catalog and coverage tooling key off.
    """
    node = next(iter(root.children()), None)
    if node is not None:
        name = node.get_property("name")
        if name and name != node.inst_name:
            return name
    return f"Address Map: {first_addrmap_name(root)}"


def addrmap_desc(root) -> str | None:
    """The map's ``desc``, rendered as an intro paragraph below the heading."""
    node = next(iter(root.children()), None)
    if node is None:
        return None
    return node.get_property("desc")


def sw_access(node) -> str:
    r = (
        "R"
        if (getattr(node, "is_sw_readable", False) or getattr(node, "has_sw_readable", False))
        else ""
    )
    w = (
        "W"
        if (getattr(node, "is_sw_writable", False) or getattr(node, "has_sw_writable", False))
        else ""
    )
    return r + w or "-"


# Write side effects that act on a single written bit render as the familiar
# merged token (RW1C, W1S, RW0C); any-write and user-defined effects, read
# effects and single-pulse render as a trailing flag so the base access stays
# byte-identical for fields that have none.
_ONWRITE_MERGE = {
    "woclr": "1C",
    "woset": "1S",
    "wot": "1T",
    "wzc": "0C",
    "wzs": "0S",
    "wzt": "0T",
}
_ONWRITE_FLAG = {"wclr": "WC", "wset": "WS", "wuser": "WMOD"}
_ONREAD_FLAG = {"rclr": "RC", "rset": "RS", "ruser": "RMOD"}


def field_access(node) -> str:
    """Software access of a field, including its read/write side effects."""
    base = sw_access(node)
    if base == "-":
        return base
    props = extract_field_props(node)
    token = base + _ONWRITE_MERGE.get(props.onwrite, "")
    flags = [token]
    if props.onwrite in _ONWRITE_FLAG:
        flags.append(_ONWRITE_FLAG[props.onwrite])
    if props.onread in _ONREAD_FLAG:
        flags.append(_ONREAD_FLAG[props.onread])
    if props.singlepulse:
        flags.append("1P")
    return " ".join(flags)


def reset_value(node) -> str:
    value = node.get_property("reset")
    if value is None:
        return "-"
    if isinstance(value, SignalNode):
        return "Signal"
    return f"0x{value:X}"


def desc_adoc(text: str | None) -> str:
    if not text:
        return "-"
    return "\n".join(
        line.strip().replace("|", r"\|") for line in text.replace("\r\n", "\n").split("\n")
    )


def desc_html(node) -> str:
    text = node.get_html_desc() if hasattr(node, "get_html_desc") else None
    return text if text is not None else escape(node.get_property("desc") or "")


def bit_ranges(reg: RegNode) -> list[Field]:
    width = reg.get_property("regwidth")
    used = [False] * width
    fields: list[tuple[int, int, FieldNode]] = []
    for f in reg.fields():
        fields.append((f.lsb, f.msb, f))
        for bit in range(f.lsb, f.msb + 1):
            used[bit] = True

    out: list[Field] = []
    by_msb = {msb: (lsb, f) for lsb, msb, f in fields}
    bit = width - 1
    while bit >= 0:
        if bit in by_msb:
            lsb, f = by_msb[bit]
            bits = f"{bit}:{lsb}" if bit != lsb else str(bit)
            out.append(
                Field(
                    bits, f.inst_name, field_access(f), reset_value(f), f.get_property("desc") or ""
                )
            )
            bit = lsb - 1
            continue
        start = bit
        while bit >= 0 and not used[bit]:
            bit -= 1
        end = bit + 1
        bits = f"{start}:{end}" if start != end else str(start)
        out.append(Field(bits, "Reserved", "-", "-", "Reserved"))
    return out


def array_ancestor(node: RegNode):
    """Nearest enclosing array (a regfile or memory replicated per index), if any."""
    parent = node.parent
    while parent is not None and not isinstance(parent, (AddrmapNode, RootNode)):
        if getattr(parent, "is_array", False):
            return parent
        parent = parent.parent
    return None


class Collector(RDLListener):
    def __init__(self, overrides: dict[str, str] | None = None):
        self.regs: list[Reg] = []
        self.arrays: dict[str, tuple[int, str, str | None]] = {}
        self.seen: set[str] = set()
        self.qualified_names: dict[str, str] = {}
        self.overrides = overrides or {}
        self.used_overrides: set[str] = set()

    def enter_Reg(self, node: RegNode):
        if node.is_array and any(i != 0 for i in (node.current_idx or [])):
            return

        # A register inside an array of regfiles is replicated the same way an
        # array of registers is, so document one entry with the enclosing stride
        # rather than one entry per index.
        enclosing = array_ancestor(node)
        if (
            not node.is_array
            and enclosing is not None
            and any(i != 0 for i in (enclosing.current_idx or []))
        ):
            return

        if node.is_array or enclosing is not None:
            dim_node = node if node.is_array else enclosing
            count = dim_node.array_dimensions[0] if dim_node.array_dimensions else 1
            stride = getattr(dim_node, "array_stride", 0) or 0
            base = node.absolute_address
            last = base + (count - 1) * stride
            if node.is_array:
                name = f"{node.get_path_segment(array_suffix='')}[{count}]"
            else:
                name = f"{enclosing.get_path_segment(array_suffix='')}[{count}].{node.inst_name}"
            addr = f"0x{base:X} - 0x{last:X}"
            self.arrays[node.get_path()] = (
                count,
                f"0x{base:X}",
                f"0x{stride:X}" if stride else None,
            )
        else:
            name = node.inst_name
            addr = f"0x{node.absolute_address:X}"

        path = node.get_path()
        if path in self.seen:
            return
        self.seen.add(path)
        qualified = path.split(".")[1:]
        if node.is_array or enclosing is not None:
            array_index = len(dim_node.get_path().split(".")) - 2
            qualified[array_index] = f"{dim_node.inst_name}[{count}]"
        self.qualified_names[path] = ".".join(qualified)
        selector = ".".join(re.sub(r"\[\d+\]$", "", segment) for segment in path.split(".")[1:])
        description = node.get_property("desc") or ""
        if selector in self.overrides:
            if description:
                raise ValueError(
                    f"{selector}: documentation override is redundant with an RDL description"
                )
            description = self.overrides[selector]
            self.used_overrides.add(selector)
        self.regs.append(
            Reg(
                name,
                addr,
                sw_access(node),
                description,
                path,
                bit_ranges(node),
            )
        )


def collect(root, overrides: dict[str, str] | None = None) -> Collector:
    c = Collector(overrides)
    RDLWalker(unroll=True).walk(root, c)
    counts = Counter(reg.name for reg in c.regs)
    for reg in c.regs:
        if counts[reg.name] > 1:
            reg.name = c.qualified_names[reg.path]
    c.arrays = {reg.name: c.arrays[reg.path] for reg in c.regs if reg.path in c.arrays}
    unmatched = set(c.overrides) - c.used_overrides
    if unmatched:
        raise ValueError(
            "documentation override selectors matched no register: " + ", ".join(sorted(unmatched))
        )
    return c


def write_adoc(root, out: str, overrides: dict[str, str] | None = None):
    data = collect(root, overrides)
    ident = first_addrmap_name(root)
    anchors = {
        r.path: "reg-{regmap-instance}-" + re.sub(r"[^A-Za-z0-9_-]+", "-", r.path)
        for r in data.regs
    }
    lines: list[str] = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        ":regmap-instance: {counter:regmap-number}",
        "",
        f"[#regmap-{{regmap-instance}}-{ident}]",
        f"== {addrmap_heading(root)}",
        "",
    ]
    desc = addrmap_desc(root)
    if desc:
        lines += [desc_adoc(desc), ""]
    if data.arrays:
        lines += [
            "[NOTE]",
            "======",
            "*Register Arrays:*",
            "",
        ]
        for name, (count, base, stride) in data.arrays.items():
            extra = f", stride {stride}" if stride else ""
            lines.append(f"* *{name}*: {count} registers, base {base}{extra}")
        lines.append("======\n")
    lines += [
        '[cols="1,4,1,6", options="header"]',
        "|===",
        "| Address | Name | Access | Description",
    ]
    lines += [
        f"| {r.addr} | <<{anchors[r.path]},{r.name}>> | {r.access} a| {desc_adoc(r.desc)}"
        for r in data.regs
    ]
    lines.append("|===\n")
    for r in data.regs:
        lines += [
            f"[#{anchors[r.path]}]",
            f"=== {r.name}",
            "",
            '[cols="1,3,1,1,6", options="header"]',
            "|===",
            "| Bits | Field | Access | Reset | Description",
        ]
        lines += [
            f"| {f.bits} | `{f.name}` | {f.access} | {f.reset} a| {desc_adoc(f.desc)}"
            for f in r.fields
        ]
        lines.append("|===\n")
    Path(out).write_text("\n".join(lines))


def write_html(root, out: str, ident: str | None = None, overrides: dict[str, str] | None = None):
    data = collect(root, overrides)
    ident = ident or first_addrmap_name(root)
    lines = [
        "<!-- SPDX-License-Identifier: Apache-2.0 -->",
        "<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->",
        '<div class="ocah-reg-html">',
        "<style>",
        ".ocah-reg-html table{width:100%;border-collapse:collapse;background:#f4f4f4}",
        ".ocah-reg-html th,.ocah-reg-html td{border:1px solid #333;padding:4px;font-family:Arial,Helvetica,sans-serif}",
        ".ocah-reg-html th{background:#81BCE5;text-align:left}",
        "</style>",
        f'<h2 id="regmap-{escape(ident)}">{escape(addrmap_heading(root))}</h2>',
    ]
    desc = addrmap_desc(root)
    if desc:
        lines.append(f"<p>{desc_html_text(desc)}</p>")
    if data.arrays:
        lines += ["<p><strong>Register Arrays:</strong></p>", "<ul>"]
        for name, (count, base, stride) in data.arrays.items():
            extra = f", stride {escape(stride)}" if stride else ""
            lines.append(
                f"<li><strong>{escape(name)}</strong>: {count} registers, base {escape(base)}{extra}</li>"
            )
        lines.append("</ul>")
    lines += [
        "<p><strong>Register List:</strong></p>",
        "<table>",
        "<tr><th>Address</th><th>Name</th><th>Access</th><th>Description</th></tr>",
    ]
    for r in data.regs:
        anchor = escape(r.name.replace("[", "_").replace("]", "_"))
        lines.append(
            f'<tr><td>{escape(r.addr)}</td><td><a href="#{anchor}">{escape(r.name)}</a></td><td>{escape(r.access)}</td><td>{desc_html_text(r.desc)}</td></tr>'
        )
    lines += ["</table>", "<p><strong>Register Details:</strong></p>"]
    for r in data.regs:
        anchor = escape(r.name.replace("[", "_").replace("]", "_"))
        lines += [
            f'<h3 id="{anchor}">{escape(r.name)}</h3>',
            "<table>",
            "<tr><th>Bits</th><th>Field</th><th>Access</th><th>Reset</th><th>Description</th></tr>",
        ]
        for f in r.fields:
            lines.append(
                f"<tr><td>{escape(f.bits)}</td><td>{escape(f.name)}</td><td>{escape(f.access)}</td><td>{escape(f.reset)}</td><td>{desc_html_text(f.desc)}</td></tr>"
            )
        lines.append("</table>")
    lines.append("</div>")
    Path(out).write_text("\n".join(lines))


def desc_html_text(text: str | None) -> str:
    return "<br>".join(
        escape(line.strip()) for line in (text or "-").replace("\r\n", "\n").split("\n")
    )
