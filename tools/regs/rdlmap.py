#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate validated subsystem memory-map AsciiDoc or JSON from SystemRDL."""

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
    render_json,
)


def _resolve(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _parameters(values: list[str]) -> dict[str, int]:
    result = {}
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name:
            raise ValueError(f"invalid parameter override {value!r}; expected NAME=VALUE")
        result[name] = int(raw, 0)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rdl", nargs="?", help="Primary RDL source")
    parser.add_argument("out")
    parser.add_argument("--config", required=True)
    parser.add_argument("-u", "--udp-rdl-file")
    parser.add_argument("-i", "-I", "--incdir", action="append", default=[])
    parser.add_argument("-t", "--top")
    parser.add_argument("-P", "--parameter", action="append", default=[])
    parser.add_argument("--view", action="append", default=[])
    parser.add_argument("--format", choices=("adoc", "json"), default="adoc")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    config_path = _resolve(args.config, repo_root)
    config = load_config(config_path)
    udp = _resolve(args.udp_rdl_file, repo_root) if args.udp_rdl_file else None
    global_incdirs = [_resolve(path, repo_root) for path in args.incdir]

    roots = {}
    source_specs = config.get("sources", ())
    if source_specs:
        for source in source_specs:
            source_incdirs = global_incdirs + [
                _resolve(path, repo_root) for path in source.get("incdirs", ())
            ]
            roots[source["name"]] = compile_root(
                _resolve(source["rdl"], repo_root),
                udp,
                source_incdirs,
                source.get("top"),
                {
                    **_parameters(args.parameter),
                    **{
                        name: int(value, 0) if isinstance(value, str) else value
                        for name, value in source.get("parameters", {}).items()
                    },
                },
            )
    else:
        if not args.rdl:
            parser.error("rdl is required when the config has no [[sources]]")
        roots["main"] = compile_root(
            _resolve(args.rdl, repo_root),
            udp,
            global_incdirs,
            args.top,
            _parameters(args.parameter),
        )

    views = build_views(config, roots)
    if args.view:
        wanted = set(args.view)
        views = [view for view in views if view.name in wanted]
        missing = wanted - {view.name for view in views}
        if missing:
            raise ValueError(f"unknown view(s): {', '.join(sorted(missing))}")

    content = render_adoc(views) if args.format == "adoc" else render_json(views)
    output = _resolve(args.out, repo_root)
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            print(f"{output}: generated memory map is stale", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
