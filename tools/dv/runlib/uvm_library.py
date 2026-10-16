# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The UVM library an SV-UVM build compiles from source.

``[build.uvm_library]`` pins a release archive by ``url`` and ``sha256``. The coordinator
fetches it once into ``local/uvm/<digest>/`` before the first stage, and later runs reuse that
copy. Build stages, farm workers among them, only read it. ``OCAH_UVM_HOME`` names a UVM home
to compile instead, for hosts that cannot reach the archive.

A UVM home holds ``src/uvm_pkg.sv`` and ``src/dpi/``, the layout of an Accellera release.
"""

from __future__ import annotations

import hashlib
import os
import re
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import ConfigError
from .paths import repo_rel

UVM_HOME_ENV = "OCAH_UVM_HOME"

_ARCHIVE_KEYS = {"url", "sha256"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FETCH_TIMEOUT_SEC = 60


def _archive(build: dict[str, Any], where: str) -> tuple[str, str]:
    table = build.get("uvm_library")
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: a UVM build needs [build.uvm_library] or [build.vcs].uvm_lib")
    unknown = sorted(set(table) - _ARCHIVE_KEYS)
    if unknown:
        raise ConfigError(f"{where}: [build.uvm_library] has unknown keys: {', '.join(unknown)}")
    url = str(table.get("url", "")).strip()
    sha256 = str(table.get("sha256", "")).strip()
    if not url:
        raise ConfigError(f"{where}: [build.uvm_library].url is required")
    if not _SHA256.fullmatch(sha256):
        raise ConfigError(
            f"{where}: [build.uvm_library].sha256 must be 64 lowercase hexadecimal digits"
        )
    return url, sha256


def _override() -> str:
    return os.environ.get(UVM_HOME_ENV, "").strip()


def uvm_home(root: Path, build: dict[str, Any], where: str) -> Path:
    """``OCAH_UVM_HOME`` when it is set, else the cache entry of the pinned archive."""
    _, sha256 = _archive(build, where)
    if _override():
        return Path(_override()).expanduser()
    return root / "local" / "uvm" / sha256[:16]


def uvm_library_src(root: Path, build: dict[str, Any], where: str, *, present: bool = True) -> Path:
    """The ``src`` directory of the UVM home; ``present`` requires its ``uvm_pkg.sv``."""
    home = uvm_home(root, build, where)
    src = home / "src"
    if present and not (src / "uvm_pkg.sv").is_file():
        if _override():
            raise ConfigError(f"{where}: {UVM_HOME_ENV}={home} has no src/uvm_pkg.sv")
        raise ConfigError(
            f"{where}: the UVM library is not fetched into {repo_rel(root, home)}; "
            f"a run without --dry-run fetches it, or {UVM_HOME_ENV} names a UVM home"
        )
    return src


def fetch_uvm_library(
    root: Path,
    build: dict[str, Any],
    where: str,
    *,
    say: Callable[[str], None] = print,
) -> Path:
    """Fetch the pinned archive unless the UVM home already holds the library; return its src.

    The archive unpacks into a temporary directory beside the cache entry and is renamed into
    place, so a concurrent fetch in the same checkout never sees a partial tree.
    """
    home = uvm_home(root, build, where)
    if _override() or (home / "src" / "uvm_pkg.sv").is_file():
        return uvm_library_src(root, build, where)
    url, sha256 = _archive(build, where)
    say(f"fetching the UVM library from {url}")
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=home.parent, prefix=".fetch-") as tmp:
        archive = Path(tmp) / "archive"
        digest = _download(url, archive, where)
        if digest != sha256:
            raise ConfigError(
                f"{where}: {url} has SHA-256 {digest}; [build.uvm_library] pins {sha256}"
            )
        unpacked = Path(tmp) / "unpacked"
        unpacked.mkdir()
        try:
            with tarfile.open(archive) as tar:
                tar.extractall(unpacked, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise ConfigError(f"{where}: cannot unpack {url}: {exc}") from exc
        try:
            _home_in(unpacked, url, where).rename(home)
        except OSError:
            if not (home / "src" / "uvm_pkg.sv").is_file():
                raise
    return home / "src"


def _download(url: str, dest: Path, where: str) -> str:
    digest = hashlib.sha256()
    try:
        with (
            urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SEC) as response,
            dest.open("wb") as out,
        ):
            while chunk := response.read(1 << 16):
                digest.update(chunk)
                out.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        raise ConfigError(
            f"{where}: cannot fetch the UVM library from {url}: {exc}; "
            f"{UVM_HOME_ENV} names a UVM home to use instead"
        ) from exc
    return digest.hexdigest()


def _home_in(unpacked: Path, url: str, where: str) -> Path:
    """The archive's UVM home: its top directory or the one directory below it."""
    candidates = [unpacked, *sorted(path for path in unpacked.iterdir() if path.is_dir())]
    for candidate in candidates:
        if (candidate / "src" / "uvm_pkg.sv").is_file():
            return candidate
    raise ConfigError(f"{where}: {url} has no src/uvm_pkg.sv at its top or one level below")
