# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.rdlview import compile_root, parse_rdl_params, write_adoc  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Emit compact AsciiDoc register tables from RDL.")
    p.add_argument("rdl")
    p.add_argument("out")
    p.add_argument("-u", "--udp-rdl-file")
    p.add_argument("-i", "-I", "--incdir", action="append", default=[])
    p.add_argument("-t", "--top")
    p.add_argument("-P", dest="rdl_params", action="append", default=[], metavar="NAME=VALUE")
    args = p.parse_args()
    write_adoc(
        compile_root(
            args.rdl,
            args.udp_rdl_file,
            args.incdir,
            args.top,
            parse_rdl_params(args.rdl_params),
        ),
        args.out,
    )


if __name__ == "__main__":
    main()
