#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Create the generated DV Python namespace bridge.

The bridge lives under ``build/dv/python`` and maps stable import names
to DUT-local DV roots, for example ``smc`` -> ``hw/sys/smc/dv``. The
generated tree is gitignored.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

NAMESPACE_ROOT = Path("build/dv/python")
DIRECT_HW_EXCLUDES = {"common", "dv", "ip", "comp", "periph", "sys"}
NESTED_HW_ROOTS = ("sys", "ip", "comp", "periph")


class NamespaceError(Exception):
    """Raised when the namespace bridge cannot be generated or validated."""


@dataclass(frozen=True)
class NamespaceTarget:
    name: str
    path: Path
    source: str


def find_repo_root(start: Path) -> Path:
    """Find the repository root from ``start``."""

    current = start.resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "Bender.yml").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate

    raise NamespaceError(f"could not find repository root from {start}")


def _add_target(
    targets: dict[str, NamespaceTarget],
    name: str,
    path: Path,
    source: str,
) -> None:
    existing = targets.get(name)
    if existing is not None and existing.path != path:
        raise NamespaceError(
            "namespace collision for "
            f"{name}: {existing.path} ({existing.source}) vs {path} ({source})"
        )

    targets[name] = NamespaceTarget(name=name, path=path, source=source)


def discover_targets(repo_root: Path) -> dict[str, NamespaceTarget]:
    """Discover DV directories exposed as import roots."""

    targets: dict[str, NamespaceTarget] = {}

    hw_root = repo_root / "hw"
    if not hw_root.is_dir():
        return targets

    for child in sorted(hw_root.iterdir()):
        if not child.is_dir() or child.name in DIRECT_HW_EXCLUDES:
            continue

        dv_root = child / "dv"
        if dv_root.is_dir():
            _add_target(targets, child.name, dv_root, f"hw/{child.name}/dv")

    for group in NESTED_HW_ROOTS:
        group_root = hw_root / group
        if not group_root.is_dir():
            continue

        for child in sorted(group_root.iterdir()):
            if not child.is_dir():
                continue

            dv_root = child / "dv"
            if dv_root.is_dir():
                _add_target(targets, child.name, dv_root, f"hw/{group}/{child.name}/dv")

    prim_root = hw_root / "common" / "prim"
    if prim_root.is_dir():
        for child in sorted(prim_root.iterdir()):
            if not child.is_dir():
                continue

            dv_root = child / "dv"
            if dv_root.is_dir():
                _add_target(targets, child.name, dv_root, f"hw/common/prim/{child.name}/dv")

    return targets


def _relative_target(link_path: Path, target_path: Path) -> str:
    return os.path.relpath(target_path, link_path.parent)


def _expected_link_target(link_path: Path, target_path: Path) -> Path:
    return (link_path.parent / os.readlink(link_path)).resolve()


def validate_existing_bridge(repo_root: Path, targets: dict[str, NamespaceTarget]) -> list[str]:
    """Return a list of validation errors for the generated namespace bridge."""

    errors: list[str] = []
    namespace_root = repo_root / NAMESPACE_ROOT

    if not namespace_root.is_dir():
        errors.append(f"missing namespace root: {namespace_root}")
        return errors

    expected_names = set(targets)

    for target in targets.values():
        link_path = namespace_root / target.name
        if not link_path.is_symlink():
            if link_path.exists():
                errors.append(f"namespace entry exists but is not a symlink: {link_path}")
            else:
                errors.append(f"missing namespace symlink: {link_path}")
            continue

        actual = _expected_link_target(link_path, target.path)
        if actual != target.path.resolve():
            errors.append(
                f"stale namespace symlink: {link_path} -> {actual}, expected {target.path}"
            )

    for entry in namespace_root.iterdir():
        if entry.name in expected_names:
            continue
        if entry.is_symlink():
            errors.append(f"stale namespace symlink: {entry}")
        else:
            errors.append(f"unexpected namespace entry: {entry}")

    return errors


def sync_bridge(repo_root: Path, targets: dict[str, NamespaceTarget]) -> None:
    """Create, refresh, and clean the generated namespace bridge."""

    if os.name == "nt":
        raise NamespaceError("Windows symlink support is out of scope for the namespace bridge")

    namespace_root = repo_root / NAMESPACE_ROOT
    namespace_root.mkdir(parents=True, exist_ok=True)

    expected_names = set(targets)

    for entry in namespace_root.iterdir():
        if entry.name in expected_names:
            continue
        if entry.is_symlink():
            entry.unlink()
        else:
            raise NamespaceError(f"unexpected non-symlink namespace entry: {entry}")

    for target in targets.values():
        link_path = namespace_root / target.name
        desired = _relative_target(link_path, target.path)

        if link_path.is_symlink():
            if os.readlink(link_path) != desired:
                link_path.unlink()
                link_path.symlink_to(desired, target_is_directory=True)
            continue

        if link_path.exists():
            raise NamespaceError(f"namespace entry exists but is not a symlink: {link_path}")

        link_path.symlink_to(desired, target_is_directory=True)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or validate build/dv/python symlinks.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="repository root; auto-detected when omitted",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the namespace bridge without modifying files",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress success output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        repo_root = find_repo_root(args.repo_root or Path.cwd())
        targets = discover_targets(repo_root)

        if args.check:
            errors = validate_existing_bridge(repo_root, targets)
            if errors:
                raise NamespaceError("\n".join(errors))
        else:
            sync_bridge(repo_root, targets)

        if not args.quiet:
            action = "validated" if args.check else "synced"
            print(f"DV Python namespace {action}: {repo_root / NAMESPACE_ROOT}")
            print(f"Mapped packages: {', '.join(sorted(targets)) or '<none>'}")
        return 0
    except NamespaceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
