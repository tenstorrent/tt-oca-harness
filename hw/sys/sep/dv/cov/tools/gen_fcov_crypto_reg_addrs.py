#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write tb/sep_fcov_crypto_reg_addrs.svh from the generated register map.

The FCOV sampler classifies the start of an inbound burst into the crypto
region as a register or a hole (``sep_fabric_inbound_aperture_cg.cp_burst_region``).
The include lists every ``*_REG_ADDR`` symbol and every ``*_MEM_BASE_ADDR`` /
``*_MEM_SIZE`` memory window (OTBN IMEM and DMEM, the HMAC and KMAC message
FIFOs, the KMAC state, the ABR key and message windows) of the OTBN, HMAC,
KMAC, entropy source and ABR units of ``hw/sys/sep/regs/gen/svh/sep_reg.svh``
by name, so a moved register or window keeps its class.

The include also gives the first and last byte of each unit aperture of the
``sep-components`` view of ``hw/sys/sep/regs/gen/py/sep_memory_map.py``
(``FapBase<Unit>`` / ``FapLast<Unit>``). The FCOV samplers classify addresses
by these apertures; the register-block sizes of ``sep_top_addrmap_pkg`` are
smaller than the apertures.

Run it after a register or map change; ``--check`` exits 1 when the committed
include differs from the generated map.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import sys

UNITS = ("OTBN", "HMAC", "KMAC", "ENTROPY_SOURCE", "ABR")
ROOT = pathlib.Path(__file__).resolve().parents[6]
SVH = ROOT / "hw/sys/sep/regs/gen/svh/sep_reg.svh"
OUT = ROOT / "hw/sys/sep/dv/tb/sep_fcov_crypto_reg_addrs.svh"
MAP_PY = ROOT / "hw/sys/sep/regs/gen/py/sep_memory_map.py"


def apertures() -> list[tuple[str, int, int]]:
    """``(CamelName, base, last)`` of every unit aperture of the component view."""
    spec = importlib.util.spec_from_file_location("sep_memory_map", MAP_PY)
    assert spec is not None and spec.loader is not None, MAP_PY
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = []
    for row in mod.VIEWS["sep-components"]["rows"]:
        if row["kind"] != "node":
            continue
        unit = row["key"].split(":", 1)[1]
        out.append(("".join(w.capitalize() for w in unit.split("_")), row["base"], row["end"]))
    return out


def render() -> str:
    text = SVH.read_text()
    names: list[str] = []
    windows: list[str] = []
    for unit in UNITS:
        names += re.findall(rf"^localparam int unsigned ({unit}_\w+_REG_ADDR)\s", text, re.M)
        windows += re.findall(rf"^localparam int unsigned ({unit}_\w+)_MEM_BASE_ADDR\s", text, re.M)
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//",
        "// Written by cov/tools/gen_fcov_crypto_reg_addrs.py from sep_reg.svh and",
        "// sep_memory_map.py. Do not edit.",
        "//",
        "// First and last byte of each unit aperture (memory_map.adoc, SEP Component",
        "// Address Map).",
    ]
    for name, base, last in apertures():
        lines += [
            f"localparam logic [31:0] FapBase{name} = 32'h{base >> 16:04X}_{base & 0xFFFF:04X};",
            f"localparam logic [31:0] FapLast{name} = 32'h{last >> 16:04X}_{last & 0xFFFF:04X};",
        ]
    lines += [
        "",
        "// 1 when the 32-bit address is a register or lies in a memory window of the",
        "// OTBN, HMAC, KMAC, entropy source or ABR unit; 0 for every other address of",
        "// those units (a hole).",
        "function automatic bit fcov_crypto_reg_addr(input logic [31:0] a);",
    ]
    for w in windows:
        cond = f"  if (a >= {w}_MEM_BASE_ADDR && a - {w}_MEM_BASE_ADDR < {w}_MEM_SIZE)"
        # The layout verible-verilog-format keeps (100-column limit).
        one = f"{cond} return 1'b1;"
        lines += [one] if len(one) <= 100 else [cond, "    return 1'b1;"]
    lines.append("  case (a)")
    for i in range(0, len(names), 3):
        chunk = names[i : i + 3]
        sep = ":" if i + 3 >= len(names) else ","
        lines.append("    " + ", ".join(chunk) + sep + (" return 1'b1;" if sep == ":" else ""))
    lines += ["    default: return 1'b0;", "  endcase", "endfunction", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    want = render()
    if args.check:
        if not OUT.exists() or OUT.read_text() != want:
            print(f"{OUT} is stale; run {pathlib.Path(__file__).name}", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(want)
    return 0


if __name__ == "__main__":
    sys.exit(main())
