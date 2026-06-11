#!/usr/bin/env python3
"""Convert a raw C constants header into a flat Python constants module."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFINE_RE = re.compile(r"^#define\s+([A-Za-z_]\w*)(?:\(([^)]*)\))?\s+(.+?)\s*$")
IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")


def clean_expr(expr: str) -> str:
    """Keep simple C integer expressions readable as Python expressions."""
    expr = expr.split("//", 1)[0].strip()
    expr = re.sub(r"\b([0-9]+)[uUlL]+\b", r"\1", expr)
    expr = re.sub(r"\b(0x[0-9A-Fa-f]+)[uUlL]+\b", r"\1", expr)
    return expr


def convert_define(name: str, args: str | None, expr: str) -> list[str]:
    expr = clean_expr(expr)
    if args is None:
        return [f"{name} = {expr}"]

    arg_names = [arg.strip() for arg in args.split(",") if arg.strip()]
    if not arg_names or any(not IDENT_RE.match(arg) for arg in arg_names):
        return [f"# Skipped unsupported macro: {name}({args}) {expr}"]

    return [
        f"def {name}({', '.join(arg_names)}):",
        f"    return {expr}",
    ]


def convert_header(in_path: Path) -> str:
    lines: list[str] = [
        "# Generated from PeakRDL raw-header C output.",
        "# Do not edit by hand.",
        "",
    ]

    with in_path.open("r", encoding="utf-8") as in_file:
        for line in in_file:
            match = DEFINE_RE.match(line.strip())
            if match is None:
                continue

            converted = convert_define(*match.groups())
            lines.extend(converted)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate flat Python constants from a raw C register header."
    )
    parser.add_argument("in_file", type=Path, help="Input raw C header.")
    parser.add_argument("out_file", type=Path, help="Output Python module.")
    args = parser.parse_args()

    args.out_file.parent.mkdir(parents=True, exist_ok=True)
    args.out_file.write_text(convert_header(args.in_file), encoding="utf-8")


if __name__ == "__main__":
    main()
