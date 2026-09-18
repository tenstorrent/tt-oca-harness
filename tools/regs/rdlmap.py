#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate validated subsystem memory-map AsciiDoc from SystemRDL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.memorymap import (  # noqa: E402
    build_views,
    compile_root,
    load_config,
    render_adoc,
)
from common.rdlview import parse_rdl_params  # noqa: E402


def _resolve(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rdl", nargs="?", help="Primary RDL source")
    parser.add_argument("out")
    parser.add_argument("--config", required=True)
    parser.add_argument("-u", "--udp-rdl-file")
    parser.add_argument("-i", "-I", "--incdir", action="append", default=[])
    parser.add_argument("-t", "--top")
    parser.add_argument("-P", "--parameter", action="append", default=[])
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = _resolve(args.config, repo_root)
    config = load_config(config_path)
    udp = _resolve(args.udp_rdl_file, repo_root) if args.udp_rdl_file else None
    global_incdirs = [_resolve(path, repo_root) for path in args.incdir]
    parameters = parse_rdl_params(args.parameter)

    source_specs = config.get("sources", ())
    if source_specs:
        roots = {
            source["name"]: compile_root(
                _resolve(source["rdl"], repo_root),
                udp,
                global_incdirs,
                source.get("top"),
                parameters,
            )
            for source in source_specs
        }
    else:
        if not args.rdl:
            parser.error("rdl is required when the config has no [[sources]]")
        roots = {
            "main": compile_root(
                _resolve(args.rdl, repo_root),
                udp,
                global_incdirs,
                args.top,
                parameters,
            )
        }

    content = render_adoc(build_views(config, roots))
    output = _resolve(args.out, repo_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
