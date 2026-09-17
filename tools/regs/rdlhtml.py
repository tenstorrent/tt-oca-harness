# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.rdlview import compile_root, first_addrmap_name, parse_rdl_params, write_html  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Emit a single-file HTML register view from RDL.")
    p.add_argument("rdl")
    p.add_argument("out")
    p.add_argument("-u", "--udp-rdl-file", required=True)
    p.add_argument("-i", "-I", "--incdir", action="append", default=[])
    p.add_argument("-t", "--top")
    p.add_argument("-P", dest="rdl_params", action="append", default=[], metavar="NAME=VALUE")
    args = p.parse_args()
    root = compile_root(
        args.rdl,
        args.udp_rdl_file,
        args.incdir,
        args.top,
        parse_rdl_params(args.rdl_params),
    )
    write_html(root, args.out, args.top or first_addrmap_name(root))


if __name__ == "__main__":
    main()
