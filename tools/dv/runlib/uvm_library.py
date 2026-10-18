# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The UVM library an SV-UVM build compiles from source.

``[build].uvm_library`` names the UVM home the build compiles, a path in the checkout or an
absolute one, and ``OCAH_UVM_HOME`` names another home for one shell. A UVM home holds
``src/uvm_pkg.sv`` and ``src/dpi/``, the layout of an Accellera release.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ConfigError
from .paths import repo_path, repo_rel

UVM_HOME_ENV = "OCAH_UVM_HOME"


@dataclass(frozen=True)
class UvmLibrary:
    """The UVM home a build compiles, where it came from, and the digest of its ``src`` tree.

    ``source`` is ``config`` (``[build].uvm_library``) or ``OCAH_UVM_HOME``. ``tree_sha256``
    is empty when the tree was not read.
    """

    src: Path
    source: str
    tree_sha256: str

    def record(self, root: Path) -> dict[str, str]:
        """The ``result.json`` entry: the source, the home, and the tree digest."""
        home = self.src.parent
        return {
            "source": self.source,
            "home": repo_rel(root, home) or str(home),
            "tree_sha256": self.tree_sha256,
        }


def uvm_tree_sha256(src: Path) -> str:
    """One digest over the path and content of every file under ``src``.

    Paths enter relative to ``src``, so the digest is the same wherever the tree sits.
    """
    digest = hashlib.sha256()
    for path in sorted(path for path in src.rglob("*") if path.is_file()):
        digest.update(path.relative_to(src).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def resolve_uvm_library(
    root: Path, build: dict[str, Any], where: str, *, digest: bool = True
) -> UvmLibrary:
    """The UVM library a build compiles; ``digest`` reads its ``src`` tree for ``tree_sha256``."""
    override = os.environ.get(UVM_HOME_ENV, "").strip()
    if override:
        home, named = Path(override).expanduser(), f"{UVM_HOME_ENV}={override}"
    else:
        text = str(build.get("uvm_library", "")).strip()
        if not text:
            raise ConfigError(
                f"{where}: a UVM build needs [build].uvm_library or [build.vcs].uvm_lib"
            )
        home, named = repo_path(root, text), f"[build].uvm_library {text}"
    src = home / "src"
    if not (src / "uvm_pkg.sv").is_file():
        raise ConfigError(f"{where}: {named} has no src/uvm_pkg.sv")
    return UvmLibrary(
        src=src,
        source=UVM_HOME_ENV if override else "config",
        tree_sha256=uvm_tree_sha256(src) if digest else "",
    )
