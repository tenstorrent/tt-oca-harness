#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Emit a make depfile of a block's `` `include ``d RDLs (gcc -MMD for SystemRDL).

Collateral rules depend only on a block's top RDL, so an include-only change
does not rebuild the top collateral. This compiles the top RDL, reads the
transitive `` `include `` closure from the compiler's FileInfo, and writes

    <target1> ... <depfile>: <inc1> <inc2> ...

so make adds the includes as prerequisites of the block's outputs. The depfile
is one of its own targets, so an include change re-scans the closure. Paths are
absolute (the depfile is a gitignored build artifact). The top RDL and UDP are
excluded: they are already static prerequisites. Empty rules for includes
(gcc -MP style) let make rescan after an include is removed or relocated.
"""

import argparse
import sys
from pathlib import Path

from systemrdl import RDLCompileError, RDLCompiler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_rdl_file", help="the block's top RDL")
    parser.add_argument(
        "-u", "--udp_rdl_file", required=True, help="the PeakRDL UDP RDL file (./regblock_udps.rdl)"
    )
    parser.add_argument(
        "-i", "--incdir", action="append", default=[], help="directory to search for included files"
    )
    parser.add_argument("-o", "--output", required=True, help="depfile to write")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="make target that gains the include prerequisites (repeat once per generated output)",
    )
    args = parser.parse_args()

    rdlc = RDLCompiler()
    try:
        rdlc.compile_file(args.udp_rdl_file)
        info = rdlc.compile_file(args.input_rdl_file, incl_search_paths=args.incdir)
    except RDLCompileError:
        sys.exit(1)

    # Exclude the top RDL itself (already a static prereq) and the UDP.
    exclude = {Path(args.input_rdl_file).resolve(), Path(args.udp_rdl_file).resolve()}
    includes = sorted({Path(f).resolve() for f in info.included_files} - exclude)

    # The depfile is one of its own targets so an include change rebuilds it.
    targets = list(args.target) + [str(Path(args.output).resolve())]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        if includes:
            prereqs = " ".join(str(p) for p in includes)
            f.write(f"{' '.join(targets)}: {prereqs}\n")
            for include in includes:
                f.write(f"{include}:\n")
        else:
            f.write("# no included RDLs\n")


if __name__ == "__main__":
    main()
