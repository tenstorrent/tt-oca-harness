#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reject a module name written bare in a module-name position of the synthesis, CDC, RDC and lint
constraints.

A design that renames every module to <prefix>_<name> sets MODPREFIX (synthesis, CDC, RDC) or
PREFIX (lint) to <prefix>_, so every module name has to go through one of them:
${MODPREFIX}<name>, ${::MODPREFIX}<name>, [cdc_mod {...}], or ${PREFIX}<name> in a lint waiver.
A bare name matches nothing in the renamed netlist, and the tool drops the waiver or constraint
without an error.

The module names are the module, interface and package declarations of every tracked
SystemVerilog file. The positions are the Module, ContainerInstance, ref_name, ref, design_name
and module_name filters; -module; the brace lists of -uds_modules, -sync_cell,
configure_ip_block -names and -ignore_modules, including a bare list inside [concat ...]; and
get_designs, get_references and current_design. Tcl comments and -comment {...} text are not
positions.
"""

import re
import subprocess
import sys
from pathlib import Path

DECL_RE = re.compile(
    r"^\s*(?:(?:virtual|static|automatic)\s+)?(?:module|interface|package|macromodule|program)"
    r"\s+(?:(?:static|automatic)\s+)?([A-Za-z_][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
SV_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)

# A name, after an optional prefix variable: ${PREFIX} (lint) or ${MODPREFIX}.
NAME = r"(\$\{?(?:::)?(?:MOD)?PREFIX\}?)?([A-Za-z_]\w*)(\*?)"
SINGLE_RES = (
    re.compile(r'\bModule\s*(?:==|=~|!=|!~)\s*\\?"' + NAME),
    re.compile(r'\bContainerInstance\s*(?:==|=~)\s*\\?"' + NAME),
    re.compile(r"\b(?:ref_name|ref|design_name|module_name)\s*(?:==|=~|!=|!~)\s*\\?\"?\{?" + NAME),
    re.compile(r"-module\s+\"?" + NAME),
    re.compile(r"\b(?:get_designs|get_references|current_design)\s+\{?\"?" + NAME),
)
# A bare brace list, which may span lines. A list passed through cdc_mod does not match.
LIST_RE = re.compile(r"-(?:uds_modules|sync_cell|names|ignore_modules|module)\s+\{([^{}]*)\}")
CONCAT_RE = re.compile(r"-(?:uds_modules|sync_cell|names|ignore_modules)\s+\[concat\b")
LIST_ITEM_RE = re.compile(r"(?<![\w$])" + NAME + r"(?![\w$])")
COMMENT_ARG_RE = re.compile(r"-comment\s+\{(?:[^{}]|\{[^{}]*\})*\}")

CONSTRAINT_PATHS = (
    "hw/sys/*/synth/*",
    "hw/sys/*/cdc/*",
    "hw/sys/*/rdc/*",
    "hw/sys/*/lint/*",
    "flows/cdc/*",
    "flows/synth/constraints/*",
)
CONSTRAINT_SUFFIXES = (".tcl", ".sdc", ".vlt", ".waiver")


def tracked(*pathspecs: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *pathspecs], check=True, capture_output=True, text=True
    ).stdout
    return [p for p in out.split("\0") if p]


def module_names() -> set[str]:
    names = set()
    for name in tracked("*.sv", "*.svh", "*.v", "*.vh"):
        text = SV_COMMENT_RE.sub(" ", Path(name).read_text(errors="replace"))
        names.update(DECL_RE.findall(text))
    return names


def blank_comments(content: str, suffix: str) -> str:
    """Replace comment text with spaces, keeping every offset and newline."""

    def blank(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    if suffix == ".vlt":
        content = re.sub(r"//[^\n]*", blank, content)
    else:
        # In Tcl and the verible waiver format # starts a comment only as a command's first word.
        content = re.sub(r"(?m)^[ \t]*#[^\n]*", blank, content)
    if suffix in (".tcl", ".sdc"):
        content = COMMENT_ARG_RE.sub(blank, content)
    return content


def concat_bare_lists(code: str):
    """Yield (offset, body) for each bare {...} list inside -opt [concat ...], outside cdc_mod."""
    for match in CONCAT_RE.finditer(code):
        depth, i = 1, match.end()
        while i < len(code) and depth:
            if code[i] == "[":
                if code.startswith("cdc_mod", i + 1):
                    inner = 1
                    i += 1
                    while i < len(code) and inner:
                        inner += {"[": 1, "]": -1}.get(code[i], 0)
                        i += 1
                    continue
                depth += 1
            elif code[i] == "]":
                depth -= 1
            elif code[i] == "{":
                end = code.index("}", i)
                yield i + 1, code[i + 1 : end]
                i = end
            i += 1


def is_module(name: str, glob: str, names: set[str]) -> bool:
    if glob:
        return any(n.startswith(name) for n in names)
    return name in names


def bare_names(content: str, suffix: str, names: set[str]) -> list[tuple[int, str]]:
    """Return (line, name) for each module name written bare in a module-name position."""
    code = blank_comments(content, suffix)
    hits = []
    for pattern in SINGLE_RES:
        for match in pattern.finditer(code):
            var, name, glob = match.groups()
            if not var and is_module(name, glob, names):
                hits.append((match.start(2), name + glob))
    lists = [(m.start(1), m.group(1)) for m in LIST_RE.finditer(code)]
    for offset, body in lists + list(concat_bare_lists(code)):
        for item in LIST_ITEM_RE.finditer(body):
            var, name, glob = item.groups()
            if not var and is_module(name, glob, names):
                hits.append((offset + item.start(2), name + glob))
    return sorted({(content.count("\n", 0, start) + 1, name) for start, name in hits})


def main(paths: list[str]) -> int:
    names = module_names()
    files = paths or [p for p in tracked(*CONSTRAINT_PATHS) if p.endswith(CONSTRAINT_SUFFIXES)]
    diagnostics = []
    for name in files:
        path = Path(name)
        for line, module in bare_names(path.read_text(), path.suffix, names):
            diagnostics.append(
                f"{path}:{line}: module name {module} is bare; write it as ${{MODPREFIX}}{module},"
                f" through cdc_mod, or as ${{PREFIX}}{module} in a lint waiver"
            )
    if diagnostics:
        print("\n".join(diagnostics), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
