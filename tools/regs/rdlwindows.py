#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Size the window of every unit the maps place, and what its decoder answers there.

Each map follows its own --top: the RDL, then --pages PKG if its children own
whole 4 KiB pages, then its -I and -P options. The windows file records every
window and response, and the address width of each register block whose window
is wider than its registers need. Each PKG, a SystemVerilog package of the
windows of a page top's children, is rendered from it. Each output is rewritten
only when its content changes, so that make reruns the generators that read it
only for a real change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from systemrdl import RDLCompileError, RDLCompiler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.rdlview import parse_rdl_params  # noqa: E402
from common.windows import (  # noqa: E402
    WindowSizer,
    render_window_pkg,
    render_windows,
)


def _compile(rdl: str, udp: str, incdirs: list[str], parameters: dict[str, int]):
    compiler = RDLCompiler()
    compiler.compile_file(udp)
    info = compiler.compile_file(
        rdl, incl_search_paths=incdirs, defines={"OCAH_DOC_MEMORY_MAP": ""}
    )
    root = compiler.elaborate(parameters=parameters)
    return root.top, [rdl, *info.included_files]


def _write(path: Path, content: str) -> None:
    if not path.is_file() or path.read_text(encoding="utf-8") != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main() -> int:
    argv = sys.argv[1:]
    starts = [index for index, arg in enumerate(argv) if arg == "--top"]
    groups = [argv[start + 1 : end] for start, end in zip(starts, starts[1:] + [len(argv)])]

    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="--top RDL [--pages PKG] [-I DIR ...] [-P NAME=VALUE ...], repeated per map",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-u", "--udp-rdl-file", required=True)
    parser.add_argument("--regblocks", required=True, help="blocks with generated register RTL")
    parser.add_argument("--wrappers", required=True, help="maps whose children share their window")
    parser.add_argument(
        "--err-check-blocks", default="", help="regblocks that refuse every unmapped address"
    )
    parser.add_argument("--no-err-blocks", default="", help="regblocks that answer OKAY throughout")
    parser.add_argument("-o", "--output", required=True, help="the windows file")
    parser.add_argument("--depfile", help="make depfile of every RDL read")
    parser.add_argument("--target", help="the make target the depfile names")
    args = parser.parse_args(argv[: starts[0]] if starts else argv)
    if not groups:
        parser.error("at least one --top is required")

    top_parser = argparse.ArgumentParser(prog=f"{parser.prog} --top")
    top_parser.add_argument("rdl")
    top_parser.add_argument("--pages", metavar="PKG", type=Path)
    top_parser.add_argument("-I", "-i", "--incdir", action="append", default=[])
    top_parser.add_argument("-P", "--parameter", action="append", default=[])

    sizer = WindowSizer(
        args.regblocks.split(),
        args.wrappers.split(),
        args.err_check_blocks.split(),
        args.no_err_blocks.split(),
    )
    sources: set[str] = set()
    packages: dict[Path, str] = {}
    for group in groups:
        top = top_parser.parse_args(group)
        try:
            node, files = _compile(
                top.rdl, args.udp_rdl_file, top.incdir, parse_rdl_params(top.parameter)
            )
        except RDLCompileError:
            return 1
        sources.update(str(Path(path).resolve()) for path in files)
        sizer.add_top(node, top.pages is not None)
        if top.pages is not None:
            packages[top.pages] = node.inst_name
    sized = sizer.sized()
    if sizer.errors:
        for error in sizer.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    _write(Path(args.output), render_windows(sized))
    for path, top_name in packages.items():
        _write(path, render_window_pkg(top_name, sized))

    if args.depfile:
        prerequisites = sorted(sources)
        depfile = Path(args.depfile)
        depfile.parent.mkdir(parents=True, exist_ok=True)
        depfile.write_text(
            f"{args.target or args.output}: {' '.join(prerequisites)}\n"
            + "".join(f"{path}:\n" for path in prerequisites),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
