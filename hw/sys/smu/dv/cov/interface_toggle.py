# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Interface toggle rate of a DUT from a Verilator coverage database.

Verilator records toggle coverage one point per bit and per edge, and it
tags every signal declared in a module -- port or internal net -- with that
module's instance as its hierarchy. An integration level is graded on its
interfaces, so this keeps the points whose hierarchy is the DUT instance,
drops the names that are not in the module's port list, and folds what is
left back to the port it belongs to: a port has toggled when any one of its
bit-edge points was hit. That is the same view `tgl(portsonly)` gives urg
on VCS, where no script is needed.

    python3 hw/sys/smu/dv/cov/interface_toggle.py <run dir | merged.dat>
        [--scope smu_wrapper_uvm_top.u_dut] [--module hw/top/smu_wrapper.sv]
        [--list]

The database is `cov/merged.dat` under a `run_dv.py --cov` run directory,
the same file `verilator_coverage` reads. The port list is read from the
DUT's own source, found from the repository root above the run directory.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_SCOPE = "smu_wrapper_uvm_top.u_dut"
DEFAULT_MODULE = Path("hw/top/smu_wrapper.sv")

_RECORD = re.compile(r"^C '(.*)' (\d+)\s*$")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*")
_PORT_DECL = re.compile(r"^\s*(input|output|inout)\b(.*)$")
_UNPACKED = re.compile(r"(\s*\[[^\]]*\])+\s*$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*$")


def _fields(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in body.split("\x01"):
        if "\x02" in item:
            key, value = item.split("\x02", 1)
            out[key] = value
    return out


def module_ports(source: Path) -> set[str]:
    """Port names from an ANSI-style module header, one declaration per line."""
    ports: set[str] = set()
    in_header = False
    for line in source.read_text(encoding="utf-8").splitlines():
        if not in_header:
            in_header = line.startswith("module ")
            continue
        if line.startswith(");"):
            break
        m = _PORT_DECL.match(line.split("//", 1)[0])
        if m is None:
            continue
        decl = _UNPACKED.sub("", m.group(2).rstrip().rstrip(",)").rstrip())
        name = _IDENT.search(decl)
        if name is not None:
            ports.add(name.group(0))
    return ports


def port_toggles(dat: Path, scope: str, ports: set[str]) -> dict[str, bool]:
    """Map each port of `scope` to whether any of its bit-edge points was hit."""
    hits: dict[str, bool] = {}
    with dat.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _RECORD.match(line)
            if m is None:
                continue
            f = _fields(m.group(1))
            if f.get("t") != "toggle" or f.get("h") != scope:
                continue
            name = _NAME.match(f.get("o", ""))
            if name is None or name.group(0) not in ports:
                continue
            port = name.group(0)
            hits[port] = hits.get(port, False) or int(m.group(2)) > 0
    return hits


def _repo_root(start: Path) -> Path | None:
    for parent in [start.resolve(), *start.resolve().parents]:
        if (parent / DEFAULT_MODULE).is_file():
            return parent
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument("database", type=Path, help="run directory or merged.dat")
    ap.add_argument("--scope", default=DEFAULT_SCOPE, help="instance whose ports are graded")
    ap.add_argument(
        "--module",
        type=Path,
        help=f"source of the module instantiated at --scope (default: {DEFAULT_MODULE})",
    )
    ap.add_argument("--list", action="store_true", help="also list the ports that never toggled")
    args = ap.parse_args(argv)

    dat = args.database
    if dat.is_dir():
        dat = dat / "cov" / "merged.dat"
    if not dat.is_file():
        print(f"no coverage database at {dat}", file=sys.stderr)
        return 2

    source = args.module
    if source is None:
        root = _repo_root(dat)
        if root is None:
            print(f"no {DEFAULT_MODULE} above {dat}; pass --module", file=sys.stderr)
            return 2
        source = root / DEFAULT_MODULE
    ports = module_ports(source)
    if not ports:
        print(f"no port declarations found in {source}", file=sys.stderr)
        return 2

    hits = port_toggles(dat, args.scope, ports)
    if not hits:
        print(f"no toggle points on the ports of {args.scope} in {dat}", file=sys.stderr)
        return 2

    toggled = sum(hits.values())
    print(f"{args.scope}: {toggled} / {len(hits)} ports toggled = {100 * toggled / len(hits):.1f}%")
    silent = sorted(ports - set(hits))
    if silent:
        print(f"  {len(silent)} declared ports carry no toggle point (constant or unused)")
    if args.list:
        for port in sorted(name for name, hit in hits.items() if not hit):
            print(f"  untoggled {port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
