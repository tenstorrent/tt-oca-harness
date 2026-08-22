#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Thin entry point for the native OSS DV launcher.

Before handing off to :mod:`runlib.cli`, the bootstrap resolves the repository
root from this script's location, exports ``OCH_ROOT``, re-executes once inside
the locked uv-managed DV environment (root ``uv.lock``, dependency group
``dv``), synchronizes the generated Python namespace bridge, and prepends the
bridge to ``sys.path``/``PYTHONPATH``.

Set ``OCAH_DV_SKIP_UV=1`` to skip only the uv re-execution (for pre-provisioned
CI or manually managed environments); root export, namespace synchronization,
and Python-path setup still run.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_SENTINEL = "OCAH_DV_UV_BOOTSTRAPPED"
_SKIP_UV = "OCAH_DV_SKIP_UV"


def _find_repo_root(script: Path) -> Path:
    for candidate in script.resolve().parents:
        if (candidate / "Bender.yml").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise SystemExit(
        f"ERROR: could not find the repository root (Bender.yml + pyproject.toml) above {script}"
    )


def _reexec_in_uv_env(root: Path, script: Path) -> None:
    """Replace this process with the same invocation inside `uv run --group dv`."""
    uv = shutil.which("uv")
    if uv is None:
        print(
            "ERROR: `uv` is required to provision the locked DV Python environment.\n"
            "Install uv (https://docs.astral.sh/uv/getting-started/installation/), or set\n"
            f"{_SKIP_UV}=1 to run in a pre-provisioned environment that already "
            "provides the `dv` dependency group.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    env = dict(os.environ)
    env[_SENTINEL] = "1"
    argv = [
        uv,
        "run",
        "--project",
        str(root),
        "--locked",
        "--group",
        "dv",
        "python",
        str(script),
        *sys.argv[1:],
    ]
    os.execvpe(argv[0], argv, env)


def _setup_python_paths(root: Path) -> None:
    """Sync the namespace bridge and expose it to this process and its children."""
    import sync_python_namespace

    try:
        sync_python_namespace.sync_bridge(root, sync_python_namespace.discover_targets(root))
    except sync_python_namespace.NamespaceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    bridge = str(root / sync_python_namespace.NAMESPACE_ROOT)
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    existing = [
        entry
        for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if entry and entry != bridge
    ]
    os.environ["PYTHONPATH"] = os.pathsep.join([bridge, *existing])


def bootstrap() -> None:
    script = Path(__file__).resolve()
    root = _find_repo_root(script)
    os.environ["OCH_ROOT"] = str(root)
    if os.environ.get(_SENTINEL) != "1" and os.environ.get(_SKIP_UV) != "1":
        _reexec_in_uv_env(root, script)  # does not return
    _setup_python_paths(root)


if __name__ == "__main__":
    bootstrap()
    from runlib.cli import main

    raise SystemExit(main())
