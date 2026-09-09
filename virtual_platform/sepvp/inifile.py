# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate a per-run overlay .ini for sep-vp.

sep-vp takes a single CCI config file; there are no arbitrary command-line param
overrides. We therefore generate an overlay that ``@include``s the base
``accellera_config.ini`` and then re-states only the parameters a run wants to change.

Override semantics (verified in ``sep/utils/csml/inc/csml_config_parser.h``):
  * ``@include`` merges another file via ``std::map::insert`` — it does NOT overwrite
    keys already present.
  * A direct ``key : value`` line uses ``operator[]`` — it DOES overwrite (last-wins).
So an ``@include <base>`` followed by direct override lines reliably wins over the base.

Because ``main.cpp`` chdir()s to the directory of the ini it is given (CWD becomes the
run dir), every *relative* path the base config carries (``targets``,
``configFile``) must be re-stated here as an ABSOLUTE path. The backend does that.

Sections mirror the base file's typing: ``[bool]``/``[int]``/``[string]``/``[uint]``.

NOTE on ``@include`` resolution: the parser prepends the *including* file's directory to
the include path unconditionally — an absolute ``@include`` becomes ``<dir>//abs/...`` and
silently fails (the parser only WARNs and continues with defaults). So we never @include an
absolute path; instead :func:`stage_base_config` copies the base and everything it includes
into the run dir, and the overlay @includes the base by *basename* (resolved within the run
dir alongside its copied includes).
"""

import re
import shutil
from pathlib import Path
from typing import Iterable, Tuple

# An override is (section, key, value); section is one of bool/int/string/uint.
Override = Tuple[str, str, object]

_SECTION_ORDER = ("bool", "int", "string", "uint")
_INCLUDE_RE = re.compile(r"^\s*@include\s+(\S+)")


def stage_base_config(base_ini: Path, run_dir: Path) -> str:
    """Copy *base_ini* and everything it (recursively) ``@include``s into *run_dir*.

    Files are copied flat, by basename, so an overlay placed in *run_dir* can
    ``@include`` the base by basename and the parser's relative-include resolution finds
    both the base and its (relative) includes there. Returns the base's basename.
    Raises if any referenced include is missing (so a typo can't silently fall back to
    model defaults).
    """
    run_dir = Path(run_dir)
    seen: set[Path] = set()

    def copy_recursive(path: Path):
        path = path.resolve()
        if path in seen:
            return
        seen.add(path)
        if not path.is_file():
            raise FileNotFoundError(f"config @include target not found: {path}")
        shutil.copyfile(path, run_dir / path.name)
        for line in path.read_text().splitlines():
            m = _INCLUDE_RE.match(line)
            if m:
                copy_recursive(path.parent / m.group(1))

    base_ini = Path(base_ini)
    copy_recursive(base_ini)
    return base_ini.name


def _fmt(value) -> str:
    """Render a Python value the way the CSML ini parser expects."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        # 8-word fuse arrays etc. — JSON-ish, decimal, space after comma (matches base).
        return "[" + ", ".join(str(int(x)) for x in value) + "]"
    if isinstance(value, Path):
        return str(value)
    return str(value)


def render_overlay(include_name: str, overrides: Iterable[Override]) -> str:
    """Return overlay-ini text that ``@include``s *include_name* then applies overrides.

    *include_name* must be a basename present in the same directory as the overlay (stage
    it there with :func:`stage_base_config`). *overrides* is an iterable of
    ``(section, key, value)``; within a section the order given is preserved, and a later
    override of the same key wins (the parser keeps the last direct assignment).
    """
    by_section: dict[str, list[Tuple[str, object]]] = {s: [] for s in _SECTION_ORDER}
    for section, key, value in overrides:
        if section not in by_section:
            raise ValueError(f"unknown ini section {section!r} for key {key!r}")
        by_section[section].append((key, value))

    lines = [
        "# Auto-generated overlay for sep-vp (sepvp.inifile) — do not edit by hand.",
        f"@include {include_name}",
        "",
    ]
    for section in _SECTION_ORDER:
        entries = by_section[section]
        if not entries:
            continue
        lines.append(f"[{section}]")
        for key, value in entries:
            lines.append(f"{key} : {_fmt(value)}")
        lines.append("")
    return "\n".join(lines) + "\n"
