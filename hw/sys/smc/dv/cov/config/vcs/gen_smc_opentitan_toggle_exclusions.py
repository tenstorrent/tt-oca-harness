#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write smc_opentitan_toggle_exclusions.el from urg's toggle template.

T1 OPENTITAN-PORTS-ONLY records one rule: a design unit that comes from
OpenTitan is graded on its ports for toggle, its internals being verified
upstream. Every other unit the scope keeps is graded on all of its nets, so the
rule is applied per unit rather than through `-cm_tgl portsonly`, which is a
whole-run option, or through a `tgl(portsonly)` block in the hierarchy file,
which `hw/sys/smu/dv/cov/config/vcs/README.md` records as keeping the toggle
points of subtrees the same file drops.

Origin is read from the source, not from the unit's name: each unit below
carries a lowRISC or OpenTitan copyright line in its first lines, and the line
is checked again at generation time so a re-licensed or replaced file stops the
script rather than passing silently. UNITS names one module each; a module's
own ports stay graded and everything else it declares is excluded.

Units compiled from `vendor/lowRISC/` are all `prim*` library cells the scope
already drops, and the lowRISC-headered files under
`vendor/chipsalliance/i3c-core/` sit inside the I3C wrapper the scope drops as
a tree, so neither appears here.

Input is the template urg writes for the merged database::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl -report <dir>

which leaves fullexclude_module.tgl in the working directory. Every checksum
and entry text below comes from it.

    python3 gen_smc_opentitan_toggle_exclusions.py <template dir>
    python3 gen_smc_opentitan_toggle_exclusions.py <template dir> --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
OUT = HERE / "smc_opentitan_toggle_exclusions.el"

# module -> the source the build compiles it from. The copyright line of each is
# checked at generation time and quoted in the file.
UNITS: tuple[tuple[str, str], ...] = (
    ("i2c", "hw/ip/i2c/rtl/i2c.sv"),
    ("i2c_core", "hw/ip/i2c/rtl/i2c_core.sv"),
    ("i2c_controller_fsm", "hw/ip/i2c/rtl/i2c_controller_fsm.sv"),
    ("i2c_target_fsm", "hw/ip/i2c/rtl/i2c_target_fsm.sv"),
    ("i2c_bus_monitor", "hw/ip/i2c/rtl/i2c_bus_monitor.sv"),
    ("uart_16550", "hw/ip/uart/uart_16550/rtl/uart_16550.sv"),
    ("uart_core", "hw/ip/uart/uart_16550/rtl/uart_core.sv"),
    ("uart_rx", "hw/ip/uart/uart_16550/rtl/uart_rx.sv"),
    ("uart_tx", "hw/ip/uart/uart_16550/rtl/uart_tx.sv"),
    ("prim_clock_mux2", "hw/common/och_prim_generic/rtl/prim_clock_mux2.sv"),
)

T1 = (
    "SMC-TOGGLE-T1-OPENTITAN-PORTS-ONLY: this unit comes from OpenTitan, whose own "
    "verification covers its internals, so the package grades it on its ports and excludes "
    "the nets it declares inside. Every unit that is not from OpenTitan keeps all of its nets "
    "in the toggle score. The source's copyright line is quoted in the block above."
)

COPYRIGHT = re.compile(r"^\s*//\s*Copyright.*?(lowRISC|OpenTitan).*$", re.I | re.M)
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
PORT_NAME = re.compile(r"([A-Za-z_][A-Za-z_0-9$]*)\s*(?:\[[^\]]*\]\s*)*(?:=[^,]*)?$")
CHECKSUM_RE = re.compile(r'^// CHECKSUM: ("[^"]*")')
MODULE_RE = re.compile(r"^// MODULE: (\S+)")
TOGGLE_RE = re.compile(r"^// (Toggle (?:\[[^\]]*\] )?(\S+) .*)$")


def copyright_line(path: Path) -> str:
    """The lowRISC or OpenTitan copyright line of a source, or stop."""
    head = "\n".join(path.read_text(errors="replace").splitlines()[:12])
    m = COPYRIGHT.search(head)
    if m is None:
        raise SystemExit(f"{path} carries no lowRISC or OpenTitan copyright line")
    return m.group(0).strip().lstrip("/").strip()


def module_ports(path: Path, module: str) -> set[str]:
    """The names in a module's ANSI port list."""
    text = COMMENTS.sub("", path.read_text(errors="replace"))
    m = re.search(r"\bmodule\s+(?:automatic\s+)?" + re.escape(module) + r"\b", text)
    if m is None:
        raise SystemExit(f"{path} declares no module {module}")
    hash_pos, start = text.find("#", m.end()), text.find("(", m.end())
    if hash_pos != -1 and hash_pos < start:
        depth, j = 0, text.find("(", hash_pos)
        while j < len(text):
            depth += text[j] == "("
            depth -= text[j] == ")"
            if depth == 0:
                break
            j += 1
        start = text.find("(", j + 1)
    depth, j = 0, start
    while j < len(text):
        depth += text[j] == "("
        depth -= text[j] == ")"
        if depth == 0:
            break
        j += 1
    ports: set[str] = set()
    depth, cur = 0, ""
    for c in text[start + 1:j] + ",":
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            name = PORT_NAME.search(cur.strip())
            if name:
                ports.add(name.group(1))
            cur = ""
            continue
        cur += c
    return ports


def is_port_bit(signal: str, ports: set[str]) -> bool:
    """Whether a toggle point names a port, or a field or bit of one.

    urg reports a struct port one field at a time, `axil_req_i.ar_valid`, and a
    vector by its base name, so the leading component is what to compare.
    """
    return signal.split(".")[0].split("[")[0] in ports


def parse(template: Path) -> dict[str, tuple[str, list[tuple[str, str]]]]:
    """module -> (checksum, [(signal, entry)]) from the toggle template."""
    out: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    checksum, module = "", ""
    for line in template.read_text(errors="replace").splitlines():
        m = CHECKSUM_RE.match(line)
        if m:
            checksum = m.group(1)
            continue
        m = MODULE_RE.match(line)
        if m:
            module = m.group(1)
            out.setdefault(module, (checksum, []))
            continue
        m = TOGGLE_RE.match(line)
        if m and module:
            out[module][1].append((m.group(2), m.group(1)))
    return out


def render(template: dict[str, tuple[str, list[tuple[str, str]]]]) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- toggle inside OpenTitan units.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_opentitan_toggle_exclusions.py from urg's toggle",
        "// template; regenerate rather than edit. Each block excludes the nets a",
        "// unit of OpenTitan origin declares inside itself and keeps its ports",
        "// graded. README.md states the rule and lists the units.",
        "//==================================================",
    ]
    count = 0
    for module, relative in UNITS:
        source = ROOT / relative
        section = template.get(module)
        if section is None:
            raise SystemExit(f"the template has no MODULE {module}: dump it from this run")
        checksum, entries = section
        ports = module_ports(source, module)
        inner = [entry for signal, entry in entries if not is_port_bit(signal, ports)]
        if not inner:
            continue
        out += [
            "",
            f"CHECKSUM: {checksum}",
            f'ANNOTATION: "{T1}"',
            f'ANNOTATION: "{module}: {copyright_line(source)}"',
            f"MODULE: {module}",
        ]
        out += inner
        count += len(inner)
    return "\n".join(out) + "\n", count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template_dir", type=Path, help="holds fullexclude_module.tgl")
    ap.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = ap.parse_args()
    text, n = render(parse(args.template_dir / "fullexclude_module.tgl"))
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print(f"{OUT} is stale; rerun without --check", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.name}: {n} toggle points across {len(UNITS)} units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
