# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Interface toggle rate of a DUT from a Verilator coverage database.

Verilator records toggle coverage one point per bit and per edge. An
integration level is graded on its interfaces, so this folds those points
back to the port they belong to: a port has toggled when any one of its
bit-edge points was hit. Only points whose hierarchy is exactly the DUT
instance are ports of the DUT; anything deeper is internal logic.

    python3 hw/sys/smu/dv/cov/interface_toggle.py <run dir | merged.dat>
        [--scope smu_wrapper_uvm_top.u_dut] [--list]

The database is `cov/merged.dat` under a `run_dv.py --cov` run directory,
the same file `verilator_coverage` reads. The VCS counterpart needs no
script: `tgl(portsonly)` in the `-cm_hier` file gives urg the same view.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_SCOPE = "smu_wrapper_uvm_top.u_dut"

_RECORD = re.compile(r"^C '(.*)' (\d+)\s*$")
_PORT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*")


def _fields(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in body.split("\x01"):
        if "\x02" in item:
            key, value = item.split("\x02", 1)
            out[key] = value
    return out


def port_toggles(dat: Path, scope: str) -> dict[str, bool]:
    """Map each port of `scope` to whether any of its bit-edge points was hit."""
    ports: dict[str, bool] = {}
    with dat.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _RECORD.match(line)
            if m is None:
                continue
            f = _fields(m.group(1))
            if f.get("t") != "toggle" or f.get("h") != scope:
                continue
            name = _PORT.match(f.get("o", ""))
            if name is None:
                continue
            port = name.group(0)
            ports[port] = ports.get(port, False) or int(m.group(2)) > 0
    return ports


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument("database", type=Path, help="run directory or merged.dat")
    ap.add_argument("--scope", default=DEFAULT_SCOPE, help="instance whose ports are graded")
    ap.add_argument("--list", action="store_true", help="also list the ports that never toggled")
    args = ap.parse_args(argv)

    dat = args.database
    if dat.is_dir():
        dat = dat / "cov" / "merged.dat"
    if not dat.is_file():
        print(f"no coverage database at {dat}", file=sys.stderr)
        return 2

    ports = port_toggles(dat, args.scope)
    if not ports:
        print(f"no toggle points on {args.scope} in {dat}", file=sys.stderr)
        return 2

    toggled = sum(ports.values())
    print(
        f"{args.scope}: {toggled} / {len(ports)} ports toggled = {100 * toggled / len(ports):.1f}%"
    )
    if args.list:
        for port in sorted(name for name, hit in ports.items() if not hit):
            print(f"  untoggled {port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
