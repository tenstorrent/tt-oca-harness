#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate the TRM RTL Modules Reference pages for the HTML build.

Writes AsciiDoc pages and HTML table fragments under the staged Antora
module. The fragments are the parameter and port tables only. svdoc's
full HTML document is not published. Nothing here is committed.
"""

import argparse
import re
import sys
from html import escape
from pathlib import Path

import pyslang
from sv_comment_text import (
    DESC,
    RULE,
    clause,
    declared_name,
    first_decl,
    header_prose,
    rtl_blocks,
    rtl_sources,
)
from svdoc.ir import ModuleDoc, PackageDoc, Typedef
from svdoc.parser import (
    _find_declaration,
    _leading_doc,
    _parse_enum_values,
    _parse_params,
    _parse_ports,
    _parse_struct_fields,
    _parse_subroutine,
    _source_manager,
    _trailing_doc,
    _type_str,
    parse_file,
)
from svdoc.render_html import _params_section, _ports_section, render_package


def _package_body(pkg: PackageDoc) -> str:
    """Keep the typedef tables. The page title and the package comment are AsciiDoc."""
    page = render_package(pkg)
    body = page.split("<body>\n", 1)[1].rsplit("\n</body>", 1)[0]
    lines = body.splitlines()
    while lines and (lines[0].startswith("<h1>") or lines[0].startswith("<p>")):
        lines.pop(0)
    text = "\n".join(lines).strip()
    return text + ("\n" if text else "")


def _para_html(para: str) -> str:
    """One header paragraph. Lines starting with "- " form a list; indented lines continue an item."""
    items = []
    text = []
    for line in para.splitlines():
        if line.startswith("- "):
            items.append([line[2:]])
        elif items:
            items[-1].append(line)
        else:
            text.append(line)
    html = f"<p>{escape(' '.join(' '.join(text).split()))}</p>" if text else ""
    if items:
        lis = "".join(f"<li>{escape(' '.join(' '.join(i).split()))}</li>" for i in items)
        html += f"<ul>{lis}</ul>"
    return html


_HEADER_END_RE = re.compile(r"^\s*\)\s*;")


def _package_from_tree(tree):
    pkg = _find_declaration(tree, pyslang.syntax.SyntaxKind.PackageDeclaration)
    doc = PackageDoc(name=pkg.header.name.valueText, doc=_leading_doc(pkg))
    members = list(pkg.members)
    for i, member in enumerate(members):
        nxt = members[i + 1] if i + 1 < len(members) else pkg.endmodule
        if member.kind == pyslang.syntax.SyntaxKind.FunctionDeclaration:
            doc.subroutines.append(_parse_subroutine(member, "function"))
        elif member.kind == pyslang.syntax.SyntaxKind.TaskDeclaration:
            doc.subroutines.append(_parse_subroutine(member, "task"))
        elif member.kind == pyslang.syntax.SyntaxKind.TypedefDeclaration:
            if member.type.kind == pyslang.syntax.SyntaxKind.EnumType:
                doc.typedefs.append(
                    Typedef(
                        name=member.name.valueText,
                        doc=_leading_doc(member),
                        kind="enum",
                        base_type=_type_str(member.type.baseType) if member.type.baseType else None,
                        values=_parse_enum_values(member.type),
                    )
                )
            elif member.type.kind == pyslang.syntax.SyntaxKind.StructType:
                doc.typedefs.append(
                    Typedef(
                        name=member.name.valueText,
                        doc=_leading_doc(member),
                        kind="struct",
                        fields=_parse_struct_fields(member.type),
                    )
                )
            else:
                doc.typedefs.append(
                    Typedef(
                        name=member.name.valueText,
                        doc=_trailing_doc(nxt) or _leading_doc(member),
                        kind="alias",
                        alias_type=_type_str(member.type),
                    )
                )
    return doc


def _doc_from_tree(tree):
    """Build a doc from a tree svdoc rejected. The header is still there."""
    try:
        kind = next(
            m.kind for m in tree.root.members if hasattr(m, "header") or hasattr(m, "members")
        )
    except StopIteration:
        return None
    if kind == pyslang.syntax.SyntaxKind.ModuleDeclaration:
        mod = _find_declaration(tree, kind)
        header = mod.header
        return ModuleDoc(
            name=header.name.valueText,
            doc=_leading_doc(mod),
            params=_parse_params(header),
            ports=_parse_ports(header),
        )
    if kind == pyslang.syntax.SyntaxKind.PackageDeclaration:
        return _package_from_tree(tree)
    return None


def _parse(path: Path, include_dirs: list):
    try:
        return parse_file(str(path), include_dirs)
    except ValueError:
        tree = pyslang.syntax.SyntaxTree.fromFile(str(path), _source_manager(include_dirs))
        doc = _doc_from_tree(tree)
        if doc is None:
            raise
        return doc


def _decl_docs(path: Path, names: list) -> dict:
    """Comment on a declaration: the same-line clause, else the // block above it.

    svdoc stores the comment above a declaration on the previous one, so it
    cannot be used here.
    """
    lines = path.read_text(errors="replace").splitlines()
    start = first_decl(lines)
    if not names or start is None:
        return {}
    known = set(names)
    docs = {}
    pending = []
    i = start + 1
    while i < len(lines) and not _HEADER_END_RE.match(lines[i]):
        stripped = lines[i].strip()
        i += 1
        if stripped.startswith("//"):
            body = DESC.sub("", stripped[2:].strip()).strip()
            if body and not RULE.match(body):
                pending.append(body)
            continue
        if not stripped or stripped.startswith("`"):
            continue
        hit = declared_name(lines[i - 1].split("//", 1)[0])
        if hit in known:
            same = ""
            if "//" in stripped:
                same, i = clause(lines, i - 1)
                same = DESC.sub("", same).strip()
            if same or pending:
                docs[hit] = same or " ".join(pending)
        pending = []
    return docs


def _apply_decl_docs(path: Path, doc: ModuleDoc) -> None:
    names = [item.name for item in doc.params] + [item.name for item in doc.ports]
    found = _decl_docs(path, names)
    for item in (*doc.params, *doc.ports):
        item.doc = found.get(item.name) or None


def _module_tables(doc: ModuleDoc) -> str:
    parts = _params_section(doc.params) + _ports_section(doc.ports)
    return "\n".join(parts).strip() + ("\n" if parts else "")


def _adoc(title: str, doc: str, partial: str) -> str:
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        f"= {title}",
        "",
    ]
    text = (doc or "").strip()
    if text:
        paras = "".join(_para_html(para) for para in text.split("\n\n") if para.strip())
        lines += ["++++", paras, "++++", ""]
    if partial:
        lines += [
            "ifdef::backend-html5[]",
            "++++",
            '<div class="ocah-reg-html">',
            f"include::partial$rtl-modules/{partial}[]",
            "</div>",
            "++++",
            "endif::backend-html5[]",
            "",
        ]
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _one(path: Path, include_dirs: list, pages: Path, partials: Path, page_dir: Path):
    """Return (name, ok). On success, write the page and the table fragment."""
    try:
        doc = _parse(path, include_dirs)
    except ValueError as exc:
        return path.stem, False, str(exc)
    if isinstance(doc, ModuleDoc):
        _apply_decl_docs(path, doc)
        tables = _module_tables(doc)
    elif isinstance(doc, PackageDoc):
        tables = _package_body(doc)
    else:
        return doc.name, False, f"unsupported {type(doc).__name__}"
    partial_name = f"{doc.name}.html"
    if tables.strip():
        _write(partials / partial_name, tables)
        partial = partial_name
    else:
        partial = ""
    prose = header_prose(path.read_text(errors="replace").splitlines()) or (doc.doc or "")
    _write(pages / page_dir / f"{doc.name}.adoc", _adoc(doc.name, prose, partial))
    return doc.name, True, ""


def _index(title: str, intro: str, links: list, failures: list) -> str:
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "",
        f"= {title}",
        "",
        intro,
        "",
    ]
    for name, href in links:
        lines.append(f"* xref:{href}[{name}]")
    if failures:
        lines += ["", "svdoc could not parse:", ""]
        for name in failures:
            lines.append(f"* {name}")
    lines.append("")
    return "\n".join(lines)


_TITLES = {
    "aou": "AXI-over-UCIe",
    "sep": "SEP",
    "smc": "SMC",
    "dtp": "DTP",
    "smu": "SMU",
    "i2c": "I2C",
    "i3ccore_wrap": "I3C",
    "efuse": "eFuse",
    "drbg": "DRBG",
    "gpio": "GPIO",
    "tlul": "TL-UL",
    "ocah_prim": "ocah_prim",
    "ocah_prim_generic": "ocah_prim_generic",
    "idma_wrapper": "iDMA",
    "jtag2axi": "JTAG to AXI",
    "jtag_intf_unit": "JTAG Interface Unit",
    "jtag_ptap": "JTAG PTAP",
    "jtag_stap": "JTAG STAP",
    "uart_16550": "UART 16550",
    "uart_wrap": "UART Wrapper",
    "uart_log_engine_wrap": "UART Log Engine Wrapper",
    "log_engine": "Log Engine",
    "key_manager": "Key Manager",
    "avsbus_controller": "AVSBus Controller",
    "axi_lite_mailbox_unit": "AXI-Lite Mailbox",
    "axi_alias_remap": "AXI Alias Remap",
    "axi_window_remap": "AXI Window Remap",
    "axi_hang_detector": "AXI Hang Detector",
    "axi_filter": "AXI Filter",
    "output_remap": "Output Remap",
    "memory_interface": "Memory Interface",
    "entropy_source": "Entropy Source",
    "telemetry_receiver": "Telemetry Receiver",
    "system_timer_octs": "System Timer",
    "cross_trigger_matrix": "Cross-Trigger Matrix",
    "cross_trigger_network": "Cross-Trigger Network",
    "cross_trigger_port": "Cross-Trigger Port",
    "zeroer": "Zeroer",
    "scrambler": "Scrambler",
}


def _title(slug: str) -> str:
    return _TITLES.get(slug, slug.replace("_", " ").title())


def _includes(root: Path, rtl: Path) -> list:
    return [
        str(rtl),
        str(root / "hw/common/assert"),
        str(root / "hw/common/assert/yosys"),
        str(root / "vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl"),
        str(root / "vendor/pulp-platform/axi/upstream/include"),
        str(root / "vendor/pulp-platform/apb/upstream/include"),
        str(root / "hw/ip/efuse/rtl/svh"),
    ]


def _emit_block(root, pages, partials, rtl, slug, group):
    """Write one block page and its module pages. Return (title, href)."""
    include_dirs = _includes(root, rtl)
    links = []
    failures = []
    page_dir = Path(f"rtl-modules-reference/{group}/{slug}")
    for path in rtl_sources(rtl):
        name, ok, _err = _one(path, include_dirs, pages, partials, page_dir)
        if ok:
            links.append((name, f"rtl-modules-reference/{group}/{slug}/{name}.adoc"))
        else:
            failures.append(name)
    href = f"rtl-modules-reference/{group}/{slug}.adoc"
    _write(
        pages / href,
        _index(_title(slug), "Parsed from the RTL.", links, failures),
    )
    return _title(slug), href


def _catalog(ip, sys, common) -> str:
    def bullets(rows):
        return "\n".join(f"* xref:{href}[{title}]" for title, href in rows)

    return "\n".join(
        [
            "// SPDX-License-Identifier: Apache-2.0",
            "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
            "",
            "= RTL Modules Reference",
            "",
            "Module, parameter, and port lists generated from the RTL.",
            "",
            "[#ip]",
            "== IP",
            "",
            bullets(ip),
            "",
            "[#subsystems]",
            "== Subsystems",
            "",
            bullets(sys),
            "",
            "[#common]",
            "== Common",
            "",
            bullets(common),
            "",
        ]
    )


def _write_nav(nav: Path, ip, sys, common) -> None:
    def rows(items, depth):
        pad = "*" * depth
        return "\n".join(f"{pad} xref:{href}[{title}]" for title, href in items)

    block = "\n".join(
        [
            "* xref:rtl-modules-reference.adoc[RTL Modules Reference]",
            "** xref:rtl-modules-reference.adoc#ip[IP]",
            rows(ip, 3),
            "** xref:rtl-modules-reference.adoc#subsystems[Subsystems]",
            rows(sys, 3),
            "** xref:rtl-modules-reference.adoc#common[Common]",
            rows(common, 3),
        ]
    )
    text = nav.read_text()
    start = text.index("* xref:rtl-modules-reference.adoc[RTL Modules Reference]")
    end = text.index("* xref:ip-reference.adoc[IP Reference]")
    nav.write_text(text[:start] + block + "\n" + text[end:])


def generate(root: Path, pages: Path, partials: Path, nav: Path = None) -> int:
    groups = {"ip": [], "sys": [], "common": []}
    for group, slug, rtl in rtl_blocks(root):
        groups[group].append(_emit_block(root, pages, partials, rtl, slug, group))
    ip, sys, common = groups["ip"], groups["sys"], groups["common"]

    aou = root / "vendor/tenstorrent/aou/upstream/RTL/AOU_TOP.sv"
    name, ok, err = _one(
        aou,
        [str(aou.parent)],
        pages,
        partials,
        Path("rtl-modules-reference/sys"),
    )
    if ok:
        src = pages / "rtl-modules-reference/sys/AOU_TOP.adoc"
        text = src.read_text().replace("= AOU_TOP", "= AXI-over-UCIe", 1)
        (pages / "rtl-modules-reference/sys/aou.adoc").write_text(text)
        src.unlink()
    else:
        _write(
            pages / "rtl-modules-reference/sys/aou.adoc",
            _index("AXI-over-UCIe", "Port list of AOU_TOP.", [], [f"AOU_TOP ({err})"]),
        )
    sys.append(("AXI-over-UCIe", "rtl-modules-reference/sys/aou.adoc"))

    _write(pages / "rtl-modules-reference.adoc", _catalog(ip, sys, common))
    if nav is not None:
        _write_nav(nav, ip, sys, common)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--pages", type=Path, required=True)
    p.add_argument("--partials", type=Path, required=True)
    p.add_argument("--nav", type=Path)
    args = p.parse_args()
    try:
        return generate(args.root, args.pages, args.partials, args.nav)
    except Exception as exc:  # noqa: BLE001 — doc build must say why it stopped
        print(f"error: RTL Modules Reference: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
