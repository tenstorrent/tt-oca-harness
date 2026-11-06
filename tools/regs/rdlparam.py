#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Print one parameter of an elaborated RDL top as ``NAME=VALUE``.

The output is a PeakRDL ``-P`` override, so a block can take a parameter's
value from another block's RDL (OCAH_REG_RDL_PARAMS_<block>).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.rdlview import compile_root  # noqa: E402


def top_parameter(rdl: str, udp: str | None, incdirs: list[str], top: str, name: str) -> int:
    """Value of parameter ``name`` on the elaborated ``top`` addrmap of ``rdl``."""
    root = compile_root(rdl, udp, incdirs, top)
    for param in root.top.inst.parameters:
        if param.name == name:
            return param.get_value()
    raise SystemExit(f"error: {top} in {rdl} has no parameter {name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("rdl")
    p.add_argument("-u", "--udp-rdl-file")
    p.add_argument("-i", "-I", "--incdir", action="append", default=[])
    p.add_argument("-t", "--top", required=True)
    p.add_argument("-p", "--param", required=True, help="parameter to print")
    args = p.parse_args()
    value = top_parameter(args.rdl, args.udp_rdl_file, args.incdir, args.top, args.param)
    print(f"{args.param}={value}")


if __name__ == "__main__":
    main()
