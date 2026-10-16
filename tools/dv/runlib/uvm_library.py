# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The UVM library an SV-UVM build compiles from source.

``[build.uvm_library]`` pins a release archive by ``url`` and ``sha256``, and the ``src`` tree
the archive unpacks to by ``tree_sha256``. The coordinator fetches the archive once into
``local/uvm/<digest>/`` before the first stage, and later runs reuse that copy. Build stages,
farm workers among them, only read it. A site file's ``[uvm_library]`` table delivers the same
archive from a mirror ``url`` or a local ``archive``, or names an installed UVM ``home``, and
``OCAH_UVM_HOME`` names a home for one shell, ahead of the site file. Every tree a build
compiles is checked against ``tree_sha256``: a mismatch is an error, except under
``OCAH_UVM_HOME``, where the result carries it for the caller to report.

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ConfigError
from .paths import repo_rel

UVM_HOME_ENV = "OCAH_UVM_HOME"

_PIN_KEYS = {"url", "sha256", "tree_sha256"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FETCH_TIMEOUT_SEC = 60


@dataclass(frozen=True)
class UvmPin:
    """The release archive ``[build.uvm_library]`` pins and the ``src`` tree it unpacks to."""

    url: str
    sha256: str
    tree_sha256: str


@dataclass(frozen=True)
class UvmLibrary:
    """The UVM home a build compiles, where it came from, and the digest of its ``src`` tree.

    ``source`` is ``archive`` (the pinned archive's cache entry), ``site`` (the site file's
    ``home``) or ``OCAH_UVM_HOME``. ``tree_sha256`` is empty when the tree was not read, and
    ``pin`` is the ``tree_sha256`` the build pins.
    """

    src: Path
    source: str
    tree_sha256: str
    pin: str

    @property
    def unpinned(self) -> bool:
        """True when the tree was read and differs from the pin."""
        return bool(self.tree_sha256) and self.tree_sha256 != self.pin

    def record(self, root: Path) -> dict[str, str]:
        """The ``result.json`` entry: the source, the home, and the tree digest."""
        home = self.src.parent
        return {
            "source": self.source,
            "home": repo_rel(root, home) or str(home),
            "tree_sha256": self.tree_sha256,
        }


def _pin(build: dict[str, Any], where: str) -> UvmPin:
    table = build.get("uvm_library")
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: a UVM build needs [build.uvm_library] or [build.vcs].uvm_lib")
    unknown = sorted(set(table) - _PIN_KEYS)
    if unknown:
        raise ConfigError(f"{where}: [build.uvm_library] has unknown keys: {', '.join(unknown)}")
    url = str(table.get("url", "")).strip()
    if not url:
        raise ConfigError(f"{where}: [build.uvm_library].url is required")
    digests = {key: str(table.get(key, "")).strip() for key in ("sha256", "tree_sha256")}
    for key, value in digests.items():
        if not _SHA256.fullmatch(value):
            raise ConfigError(
                f"{where}: [build.uvm_library].{key} must be 64 lowercase hexadecimal digits"
            )
    return UvmPin(url=url, sha256=digests["sha256"], tree_sha256=digests["tree_sha256"])


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


def _override() -> str:
    return os.environ.get(UVM_HOME_ENV, "").strip()


def _locate(root: Path, pin: UvmPin, site: Mapping[str, str]) -> tuple[Path, str]:
    """The UVM home and its source: ``OCAH_UVM_HOME``, the site's ``home``, the cache entry."""
    if _override():
        return Path(_override()).expanduser(), UVM_HOME_ENV
    if site.get("home"):
        return Path(site["home"]), "site"
    return root / "local" / "uvm" / pin.sha256[:16], "archive"


def _describe(root: Path, home: Path, source: str) -> str:
    if source == UVM_HOME_ENV:
        return f"{UVM_HOME_ENV}={home}"
    if source == "site":
        return f"the site layer's [uvm_library].home {home}"
    return repo_rel(root, home) or str(home)


def resolve_uvm_library(
    root: Path,
    build: dict[str, Any],
    where: str,
    *,
    site: Mapping[str, str] | None = None,
    present: bool = True,
    verify: bool = True,
) -> UvmLibrary:
    """The UVM library a build compiles.

    ``site`` is the site file's ``[uvm_library]`` table. ``present`` requires the home's
    ``src/uvm_pkg.sv``. ``verify`` reads a tree that exists and checks it against
    ``tree_sha256``; a mismatch raises for a cache entry or a site home and marks the result
    ``unpinned`` under ``OCAH_UVM_HOME``.
    """
    pin = _pin(build, where)
    home, source = _locate(root, pin, site or {})
    src = home / "src"
    found = (src / "uvm_pkg.sv").is_file()
    if present and not found:
        if source != "archive":
            raise ConfigError(f"{where}: {_describe(root, home, source)} has no src/uvm_pkg.sv")
        raise ConfigError(
            f"{where}: the UVM library is not fetched into {_describe(root, home, source)}; "
            "a run without --dry-run fetches it, a site file's [uvm_library] delivers it, "
            f"or {UVM_HOME_ENV} names a UVM home"
        )
    tree = uvm_tree_sha256(src) if verify and found else ""
    if tree and tree != pin.tree_sha256 and source != UVM_HOME_ENV:
        moved = "; move it aside to fetch the archive again" if source == "archive" else ""
        raise ConfigError(
            f"{where}: {_describe(root, home, source)} holds a src tree with SHA-256 {tree}; "
            f"[build.uvm_library].tree_sha256 pins {pin.tree_sha256}{moved}"
        )
    return UvmLibrary(src=src, source=source, tree_sha256=tree, pin=pin.tree_sha256)


def fetch_uvm_library(
    root: Path,
    build: dict[str, Any],
    where: str,
    *,
    site: Mapping[str, str] | None = None,
    say: Callable[[str], None] = print,
) -> UvmLibrary:
    """Fill the pinned archive's cache entry when the build compiles it and it is absent.

    The archive comes from the site's ``archive`` or mirror ``url`` when it names one, else
    from the pinned ``url``; it must match ``sha256`` and unpack to ``tree_sha256``. It unpacks
    into a temporary directory beside the cache entry and is renamed into place, so a
    concurrent fetch in the same checkout never sees a partial tree. Returns the resolved
    library, verified.
    """
    site = site or {}
    pin = _pin(build, where)
    home, source = _locate(root, pin, site)
    if source == "archive" and not (home / "src" / "uvm_pkg.sv").is_file():
        url = Path(site["archive"]).as_uri() if site.get("archive") else site.get("url") or pin.url
        _fetch_into(home, pin, url, where, say)
    return resolve_uvm_library(root, build, where, site=site)


def _fetch_into(home: Path, pin: UvmPin, url: str, where: str, say: Callable[[str], None]) -> None:
    say(f"fetching the UVM library from {url}")
    home.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=home.parent, prefix=".fetch-") as tmp:
        archive = Path(tmp) / "archive"
        digest = _download(url, archive, where)
        if digest != pin.sha256:
            raise ConfigError(
                f"{where}: {url} has SHA-256 {digest}; [build.uvm_library] pins {pin.sha256}"
            )
        unpacked = Path(tmp) / "unpacked"
        unpacked.mkdir()
        try:
            with tarfile.open(archive) as tar:
                tar.extractall(unpacked, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise ConfigError(f"{where}: cannot unpack {url}: {exc}") from exc
        candidate = _home_in(unpacked, url, where)
        tree = uvm_tree_sha256(candidate / "src")
        if tree != pin.tree_sha256:
            raise ConfigError(
                f"{where}: {url} unpacks to a src tree with SHA-256 {tree}; "
                f"[build.uvm_library].tree_sha256 pins {pin.tree_sha256}"
            )
        try:
            candidate.rename(home)
        except OSError:
            if not (home / "src" / "uvm_pkg.sv").is_file():
                raise


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
            f"{where}: cannot fetch the UVM library from {url}: {exc}; a site file's "
            f"[uvm_library] names a mirror, an archive or a UVM home, or {UVM_HOME_ENV} "
            "names a UVM home to use instead"
        ) from exc
    return digest.hexdigest()


def _home_in(unpacked: Path, url: str, where: str) -> Path:
    """The archive's UVM home: its top directory or the one directory below it."""
    candidates = [unpacked, *sorted(path for path in unpacked.iterdir() if path.is_dir())]
    for candidate in candidates:
        if (candidate / "src" / "uvm_pkg.sv").is_file():
            return candidate
    raise ConfigError(f"{where}: {url} has no src/uvm_pkg.sv at its top or one level below")
