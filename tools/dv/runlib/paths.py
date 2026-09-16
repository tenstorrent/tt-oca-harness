# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Repository path helpers for the native DV runner."""

from __future__ import annotations

from pathlib import Path

from .models import ConfigError


def repo_root(start: Path) -> Path:
    cursor = start.resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "Bender.yml").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise ConfigError(f"could not find repository root from {start}")


def dv_root(root: Path) -> Path:
    """Return the DV infrastructure root (the repository root)."""
    return root


def configs_root(root: Path) -> Path:
    return dv_root(root) / "hw" / "common" / "dv" / "configs"


def dv_path(root: Path, text: str | None) -> Path:
    """Resolve a DV-root-relative path through the active DV root; absolute paths pass through."""
    if not text:
        return dv_root(root)
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    return dv_root(root) / path


def dut_build_root(dut_dv_root: Path) -> Path:
    """Per-DUT build output root: ``<dut-dv-root>/build`` (no repository-root build tree)."""
    return dut_dv_root / "build"


def dut_runs_root(dut_dv_root: Path) -> Path:
    """Per-DUT run directory root: ``<dut-dv-root>/build/runs``."""
    return dut_build_root(dut_dv_root) / "runs"


def repo_path(root: Path, text: str | None) -> Path:
    if not text:
        return root
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    return root / path


def repo_rel(root: Path, path: Path | str | None) -> str | None:
    if path is None:
        return None
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(resolved)
