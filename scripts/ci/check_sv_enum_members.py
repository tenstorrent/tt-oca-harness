#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reject SystemVerilog enum members that are not UPPER_SNAKE_CASE."""

import re
import sys
from pathlib import Path

from pyslang.syntax import SyntaxKind, SyntaxNode, SyntaxTree

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def main(paths: list[str]) -> int:
    diagnostics: list[str] = []
    for name in paths:
        path = Path(name)
        tree = SyntaxTree.fromFile(str(path))
        sources = tree.sourceManager

        def visit(node, path=path, sources=sources):
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
                location = member.name.location
                # An `include pulls other files into the tree; each file reports its own members.
                if Path(sources.getFileName(location)).resolve() != path.resolve():
                    continue
                if not UPPER_SNAKE.match(member.name.valueText):
                    line = sources.getLineNumber(location)
                    diagnostics.append(
                        f"{path}:{line}: enum member {member.name.valueText}{owner} "
                        "is not UPPER_SNAKE_CASE"
                    )

        tree.root.visit(visit)
    if diagnostics:
        print("\n".join(diagnostics), file=sys.stderr)
    return int(bool(diagnostics))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
