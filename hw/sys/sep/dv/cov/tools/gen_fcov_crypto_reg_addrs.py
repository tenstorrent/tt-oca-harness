#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write tb/sep_fcov_crypto_reg_addrs.svh from the generated register header.

The FCOV sampler classifies the start of an inbound burst into the crypto
region as a register or a hole (``sep_fabric_inbound_aperture_cg.cp_burst_region``).
The include lists every ``*_REG_ADDR`` symbol of the OTBN, HMAC, KMAC,
entropy source and ABR windows of ``hw/sys/sep/regs/gen/svh/sep_reg.svh`` by
name, so a moved register keeps its class. Run it after a register change;
``--check`` exits 1 when the committed include differs from the header.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

UNITS = ("OTBN", "HMAC", "KMAC", "ENTROPY_SOURCE", "ABR")
ROOT = pathlib.Path(__file__).resolve().parents[6]
SVH = ROOT / "hw/sys/sep/regs/gen/svh/sep_reg.svh"
OUT = ROOT / "hw/sys/sep/dv/tb/sep_fcov_crypto_reg_addrs.svh"


def render() -> str:
    text = SVH.read_text()
    names: list[str] = []
    for unit in UNITS:
        names += re.findall(rf"^localparam int unsigned ({unit}_\w+_REG_ADDR)\s", text, re.M)
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//",
        "// Written by cov/tools/gen_fcov_crypto_reg_addrs.py from sep_reg.svh. Do not edit.",
        "// 1 when the 32-bit address is a register of the OTBN, HMAC, KMAC, entropy",
        "// source or ABR window; 0 for every other address of those windows (a hole).",
        "function automatic bit fcov_crypto_reg_addr(input logic [31:0] a);",
        "  case (a)",
    ]
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
