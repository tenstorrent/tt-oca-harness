#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reject SystemVerilog enum members that are not UPPER_SNAKE_CASE and enum types that are not
lower_snake_case with an _e suffix."""

import re
import sys
from pathlib import Path

from pyslang.syntax import SyntaxKind, SyntaxNode, SyntaxTree

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")
LOWER_SNAKE_E = re.compile(r"^[a-z][a-z0-9_]*_e$")


def main(paths: list[str]) -> int:
    diagnostics: list[str] = []
    for name in paths:
        path = Path(name)
        tree = SyntaxTree.fromFile(str(path))
        sources = tree.sourceManager

        def report(token, message, path=path, sources=sources):
            location = token.location
            # An `include pulls other files into the tree; each file reports its own enums.
            if Path(sources.getFileName(location)).resolve() != path.resolve():
                return
            diagnostics.append(f"{path}:{sources.getLineNumber(location)}: {message}")

        def visit(node, report=report):
            if not isinstance(node, SyntaxNode):
                return
            if node.kind != SyntaxKind.EnumType:
                return
            parent = node.parent
            typedef = parent is not None and parent.kind == SyntaxKind.TypedefDeclaration
            owner = f" of {parent.name.valueText}" if typedef else ""
            for member in node.members:
                if not hasattr(member, "name"):
                    continue
                if not UPPER_SNAKE.match(member.name.valueText):
                    report(
                        member.name,
                        f"enum member {member.name.valueText}{owner} is not UPPER_SNAKE_CASE",
                    )
            if typedef and not LOWER_SNAKE_E.match(parent.name.valueText):
                report(
                    parent.name,
                    f"enum type {parent.name.valueText} is not lower_snake_case with an _e suffix",
                )

        tree.root.visit(visit)
    if diagnostics:
        print("\n".join(diagnostics), file=sys.stderr)
    return int(bool(diagnostics))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
