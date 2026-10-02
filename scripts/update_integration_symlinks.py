#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Regenerate the grouped integration-collateral symlink indexes."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integration"
GENERATED_ROOTS = tuple(INTEGRATION / name for name in ("rdl", "ipxact", "constraints"))
INCLUDE_RE = re.compile(r'^\s*`include\s+"([^"]+)"', re.MULTILINE)
RdlUnit = tuple[str, tuple[Path, ...]]


def repo_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def glob_many(*patterns: str) -> list[Path]:
    return sorted({path for pattern in patterns for path in ROOT.glob(pattern)})


def production_rdl_sources() -> list[Path]:
    return [
        path
        for path in glob_many(
            "hw/sys/*/regs/**/*.rdl",
            "hw/sys/*/dv/models/regs/*.rdl",
            "hw/ip/*/regs/**/*.rdl",
            "hw/ip/*/*/regs/**/*.rdl",
            "hw/ip/*/dv/models/regs/*.rdl",
            "hw/ip/*/*/dv/models/regs/*.rdl",
            "hw/common/regs/*.rdl",
            "vendor/*/*/overlay/**/*.rdl",
            "vendor/tenstorrent/aou/upstream/csr/*.rdl",
            "vendor/chipsalliance/i3c-core/upstream/src/rdl/*.rdl",
        )
        if "gen" not in path.parts and "memory_interface" not in path.parts
    ]


def discover_rdl_units() -> list[RdlUnit]:
    units: list[RdlUnit] = []

    def add(system: str, entries: tuple[Path, ...]) -> None:
        if entries:
            units.append((system, entries))

    for regs_dir in sorted(ROOT.glob("hw/sys/*/regs")):
        system = regs_dir.parent.name
        top = regs_dir / f"{system}.rdl"
        if top.exists():
            add(system, (top,))

    smu = ROOT / "hw/sys/smu/regs/include/smu.rdl"
    if smu.exists():
        add("smu", (smu,))

    systems = [system for system, _ in units]
    if len(systems) != len(set(systems)):
        raise RuntimeError("duplicate RDL unit destination")
    return units


def owner_root(path: Path) -> Path:
    relative = path.relative_to(ROOT)
    if relative.parts[:2] == ("hw", "sys"):
        return ROOT.joinpath(*relative.parts[:3])
    if relative.parts[:2] == ("hw", "ip"):
        regs_index = relative.parts.index("regs")
        return ROOT.joinpath(*relative.parts[:regs_index])
    if relative.parts[:3] == ("hw", "common", "axi"):
        return ROOT.joinpath(*relative.parts[:4])
    if relative.parts[0] == "vendor":
        if "overlay" in relative.parts:
            overlay_index = relative.parts.index("overlay")
            if "regs" in relative.parts[overlay_index + 1 :]:
                return ROOT.joinpath(*relative.parts[: overlay_index + 4])
            return ROOT.joinpath(*relative.parts[: overlay_index + 2])
        if "aou" in relative.parts:
            return ROOT / "vendor/tenstorrent/aou/upstream/csr"
        if "i3c-core" in relative.parts:
            return ROOT / "vendor/chipsalliance/i3c-core/upstream/src"
    return path.parent


def resolve_include(including: Path, include: str, candidates: dict[str, list[Path]]) -> Path:
    direct = (including.parent / include).resolve()
    if direct.is_file() and direct.is_relative_to(ROOT):
        return direct

    matches = candidates.get(Path(include).name, [])
    local_root = owner_root(including)
    local_matches = [path for path in matches if path.is_relative_to(local_root)]
    for selection in (local_matches, matches):
        if len(selection) == 1:
            return selection[0]
    if not matches:
        raise RuntimeError(f"{repo_path(including)} includes missing file {include!r}")
    locations = ", ".join(repo_path(path) for path in matches)
    raise RuntimeError(f"{repo_path(including)} includes ambiguous file {include!r}: {locations}")


def rdl_closure(entries: tuple[Path, ...], candidates: dict[str, list[Path]]) -> set[Path]:
    closure: set[Path] = set()
    pending = list(entries)
    while pending:
        source = pending.pop()
        if source in closure:
            continue
        closure.add(source)
        if source.suffix != ".rdl":
            continue
        for include in INCLUDE_RE.findall(source.read_text(encoding="utf-8")):
            include_path = Path(include)
            if include_path.parent not in (Path("."), Path("..")):
                raise RuntimeError(
                    f"{repo_path(source)} uses unsupported nested include {include!r}"
                )
            dependency = resolve_include(source, include, candidates)
            if include_path.parent == Path("..") and dependency.suffix == ".rdl":
                raise RuntimeError(
                    f"{repo_path(source)} uses unsupported parent RDL include {include!r}"
                )
            pending.append(dependency)
    return closure


def add_link(links: dict[Path, Path], destination: Path, source: Path) -> None:
    previous = links.get(destination)
    if previous is not None and previous != source:
        raise RuntimeError(
            f"{destination.as_posix()} maps to both {repo_path(previous)} and {repo_path(source)}"
        )
    links[destination] = source


def rdl_unit_closures() -> dict[str, set[Path]]:
    candidates: dict[str, list[Path]] = {}
    for source in production_rdl_sources():
        candidates.setdefault(source.name, []).append(source)
    return {system: rdl_closure(entries, candidates) for system, entries in discover_rdl_units()}


def rdl_links(units: dict[str, set[Path]]) -> dict[Path, Path]:
    # Non-RDL support files (e.g. i3c_defines.svh) sit at the rdl/ root rather
    # than in a subsystem folder: their RDL includers use a parent-relative
    # `include "../<file>"`, and every subsystem folder that needs one is one
    # directory below rdl/, so the same root copy resolves that include for
    # all of them.
    links: dict[Path, Path] = {}
    for system, sources in units.items():
        for source in sources:
            destination = (
                Path("rdl") / system / source.name
                if source.suffix == ".rdl"
                else Path("rdl") / source.name
            )
            add_link(links, destination, source)
    return links


def ipxact_links(units: dict[str, set[Path]]) -> dict[Path, Path]:
    links: dict[Path, Path] = {}
    sources = glob_many(
        "hw/sys/*/regs/gen/ipxact/*.xml",
        "hw/ip/*/regs/gen/ipxact/*.xml",
        "hw/ip/*/*/regs/gen/ipxact/*.xml",
        "vendor/*/*/overlay/**/regs/gen/ipxact/*.xml",
    )
    for system, closure in units.items():
        stems = {source.stem for source in closure if source.suffix == ".rdl"}
        for source in sources:
            if "dv" not in source.parts and source.stem in stems:
                add_link(links, Path("ipxact") / system / source.name, source)
    return links


def constraint_links() -> dict[Path, Path]:
    links: dict[Path, Path] = {}
    for sdc in sorted(ROOT.glob("hw/sys/*/synth/constraints.sdc")):
        system = sdc.parents[1].name
        synth_dir = sdc.parent
        for source in sorted(synth_dir.glob("*.sdc")) + sorted(
            synth_dir.glob(f"{system}_cdc_max_delay*.tcl")
        ):
            add_link(links, Path("constraints") / system / "synth" / source.name, source)

    for source in sorted((ROOT / "flows/synth/constraints").glob("*.tcl")):
        add_link(links, Path("constraints/shared") / source.name, source)
    return links


def desired_links() -> dict[Path, Path]:
    units = rdl_unit_closures()
    return rdl_links(units) | ipxact_links(units) | constraint_links()


def actual_links() -> dict[Path, Path]:
    links: dict[Path, Path] = {}
    for root in GENERATED_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_symlink():
                links[path.relative_to(INTEGRATION)] = path
            elif path.is_file():
                raise RuntimeError(f"generated index contains regular file: {repo_path(path)}")
    return links


def check(links: dict[Path, Path]) -> int:
    actual = actual_links()
    problems = {
        "missing": set(links) - set(actual),
        "extra": set(actual) - set(links),
        "absolute target": {
            path for path, link in actual.items() if Path(os.readlink(link)).is_absolute()
        },
        "wrong target": {
            path
            for path in set(links) & set(actual)
            if links[path].resolve() != actual[path].resolve()
        },
    }
    for label, paths in problems.items():
        for path in sorted(paths):
            print(f"{label}: integration/{path.as_posix()}", file=sys.stderr)
    return int(any(problems.values()))


def regenerate(links: dict[Path, Path]) -> None:
    for path in GENERATED_ROOTS:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)

    for relative, source in sorted(links.items()):
        destination = INTEGRATION / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = os.path.relpath(source, destination.parent)
        destination.symlink_to(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="check that the integration indexes match the discovered collateral",
    )
    args = parser.parse_args()

    try:
        links = desired_links()
        if args.check:
            return check(links)
        regenerate(links)
    except (OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"updated {len(links)} integration symlinks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
