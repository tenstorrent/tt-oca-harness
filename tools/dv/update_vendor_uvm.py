#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# update_vendor_uvm.py
#
# Vendors an Accellera UVM release into vendor/accellera/uvm-core/. Accellera publishes each
# release as an archive on its UVM download page, and bender's vendor_package fetches only
# from git. upstream/ holds the archive's src/ tree and its LICENSE.txt, NOTICE.txt and
# README.md unmodified, and release.toml records the release, the archive URL and the
# archive's SHA-256.
#
# Usage:
#   # Replace upstream/ with the newest release the download page lists
#   python3 tools/dv/update_vendor_uvm.py
#
#   # Replace it with a named release
#   python3 tools/dv/update_vendor_uvm.py --release 2020-3.2
#
#   # Download the recorded archive again and compare upstream/ with it
#   python3 tools/dv/update_vendor_uvm.py --check
#
# Exit codes:
#   0   upstream/ written, or it matches its recorded release.
#   1   upstream/ differs from its recorded release.
#   2   Download, archive or argument error.

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
import tarfile
import tomllib
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "vendor" / "accellera" / "uvm-core"
DOWNLOAD_PAGE = "https://www.accellera.org/downloads/standards/uvm"

# The download page's link text for a release archive: "UVM v2020.3.2 Library Code for
# IEEE 1800.2", and "UVM 2017 v1.1 Library Code for IEEE 1800.2" for the 2017 releases.
_RELEASE_LINK = re.compile(
    r"UVM (?:v(\d{4})\.|(\d{4}) v)(\d+)\.(\d+) Library Code for IEEE 1800\.2"
)
_KEPT_FILES = frozenset({"LICENSE.txt", "NOTICE.txt", "README.md"})
_APACHE_2 = "Apache License Version 2.0, January 2004"
_MAX_DOWNLOAD = 64 << 20

_RECORD = """\
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# The Accellera UVM release upstream/ holds unmodified. `make update-vendor-uvm` writes this
# file and upstream/ together.
release = {release}
url = {url}
sha256 = {sha256}
"""


class UpdateError(Exception):
    """A download, a listing or an archive this tool refuses."""


@dataclass(frozen=True)
class Release:
    """A release the download page links, under Accellera's name for it, such as 2020-3.2."""

    name: str
    url: str

    @property
    def order(self) -> tuple[int, ...]:
        return tuple(int(part) for part in re.split(r"[-.]", self.name))


class _Links(HTMLParser):
    """Every ``<a href>`` on a page, with its text."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def list_releases(page: str, base: str = DOWNLOAD_PAGE) -> list[Release]:
    """The UVM releases a download page links, newest first."""
    parser = _Links()
    parser.feed(page)
    releases: dict[str, Release] = {}
    for href, text in parser.links:
        match = _RELEASE_LINK.search(text)
        if match:
            name = f"{match.group(1) or match.group(2)}-{match.group(3)}.{match.group(4)}"
            releases.setdefault(name, Release(name, urljoin(base, href)))
    return sorted(releases.values(), key=lambda release: release.order, reverse=True)


def select_release(releases: list[Release], name: str | None) -> Release:
    """The release ``name`` names, or the newest one when ``name`` is None."""
    if not releases:
        raise UpdateError(f"{DOWNLOAD_PAGE} links no UVM release")
    if name is None:
        return releases[0]
    for release in releases:
        if release.name == name:
            return release
    listed = ", ".join(release.name for release in releases)
    raise UpdateError(f"{DOWNLOAD_PAGE} links no release {name}; it links {listed}")


def fetch(url: str) -> bytes:
    """The body ``url`` serves over HTTPS, at most 64 MiB."""
    if urlsplit(url).scheme != "https":
        raise UpdateError(f"{url}: only an https URL is fetched")
    request = urllib.request.Request(url, headers={"User-Agent": "tt-oca-harness"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if urlsplit(response.url).scheme != "https":
                raise UpdateError(f"{url}: redirected to {response.url}")
            body: bytes = response.read(_MAX_DOWNLOAD + 1)
    except OSError as err:
        raise UpdateError(f"{url}: {err}") from err
    if len(body) > _MAX_DOWNLOAD:
        raise UpdateError(f"{url}: larger than {_MAX_DOWNLOAD} bytes")
    return body


def is_kept(path: str) -> bool:
    """Whether ``upstream/`` keeps an archive file at ``path`` below the top directory."""
    return path.startswith("src/") or path in _KEPT_FILES


def is_apache_2(license_text: str) -> bool:
    """Whether a LICENSE file is the Apache License, Version 2.0."""
    return " ".join(license_text.split()).startswith(_APACHE_2)


def release_members(archive: bytes) -> dict[str, bytes]:
    """The files ``upstream/`` keeps from a release archive, by path below its top directory.

    The archive holds one top directory and no member outside it, and every kept member is a
    regular file. LICENSE.txt is the Apache License, Version 2.0, and src/uvm_pkg.sv exists.
    """
    try:
        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:*")
    except tarfile.TarError as err:
        raise UpdateError(f"the archive is not a tar archive: {err}") from err
    members: dict[str, bytes] = {}
    with tar:
        entries = [(entry, PurePosixPath(entry.name).parts) for entry in tar.getmembers()]
        for entry, parts in entries:
            if PurePosixPath(entry.name).is_absolute() or ".." in parts:
                raise UpdateError(f"archive member {entry.name} leaves the archive")
        tops = {parts[0] for _, parts in entries if parts}
        if len(tops) != 1:
            raise UpdateError(f"the archive holds {len(tops)} top-level entries, not one")
        for entry, parts in entries:
            path = "/".join(parts[1:])
            if not is_kept(path) or entry.isdir():
                continue
            if not entry.isfile():
                raise UpdateError(f"archive member {entry.name} is not a regular file")
            if path in members:
                raise UpdateError(f"the archive holds {entry.name} twice")
            data = tar.extractfile(entry)
            assert data is not None
            members[path] = data.read()
    if "src/uvm_pkg.sv" not in members:
        raise UpdateError("the archive has no src/uvm_pkg.sv")
    if not is_apache_2(members.get("LICENSE.txt", b"").decode("utf-8", "replace")):
        raise UpdateError("the archive's LICENSE.txt is not the Apache License, Version 2.0")
    return members


def tree_files(root: Path) -> dict[str, bytes | None]:
    """Every file below ``root`` by relative path; a symbolic link reads as None."""
    return {
        path.relative_to(root).as_posix(): None if path.is_symlink() else path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_symlink() or path.is_file()
    }


def differences(expected: dict[str, bytes], actual: dict[str, bytes | None]) -> list[str]:
    """One line for each path where ``actual`` departs from ``expected``."""
    lines = [f"missing {path}" for path in sorted(expected.keys() - actual.keys())]
    lines += [f"extra {path}" for path in sorted(actual.keys() - expected.keys())]
    lines += [
        f"differs {path}"
        for path in sorted(expected.keys() & actual.keys())
        if expected[path] != actual[path]
    ]
    return lines


def read_record(package: Path) -> dict[str, Any]:
    """The release ``package/release.toml`` records."""
    path = package / "release.toml"
    try:
        record = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise UpdateError(f"{path}: {err}") from err
    missing = [key for key in ("release", "url", "sha256") if not isinstance(record.get(key), str)]
    if missing:
        raise UpdateError(f"{path}: no {', '.join(missing)}")
    return record


def update(package: Path, name: str | None) -> tuple[Release, int]:
    """Replace ``package/upstream`` with a release and record it; the release and its file count."""
    page = fetch(DOWNLOAD_PAGE).decode("utf-8", "replace")
    release = select_release(list_releases(page), name)
    archive = fetch(release.url)
    members = release_members(archive)
    staging = package / "upstream.new"
    if staging.exists():
        shutil.rmtree(staging)
    for path, data in members.items():
        (staging / path).parent.mkdir(parents=True, exist_ok=True)
        (staging / path).write_bytes(data)
    if (package / "upstream").exists():
        shutil.rmtree(package / "upstream")
    staging.rename(package / "upstream")
    record = _RECORD.format(
        release=json.dumps(release.name),
        url=json.dumps(release.url),
        sha256=json.dumps(hashlib.sha256(archive).hexdigest()),
    )
    (package / "release.toml").write_text(record, encoding="utf-8")
    return release, len(members)


def check(package: Path) -> list[str]:
    """How ``package/upstream`` departs from the archive ``release.toml`` records."""
    record = read_record(package)
    archive = fetch(record["url"])
    digest = hashlib.sha256(archive).hexdigest()
    if digest != record["sha256"]:
        return [f"{record['url']} serves sha256 {digest}, not the recorded {record['sha256']}"]
    return differences(release_members(archive), tree_files(package / "upstream"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Vendor an Accellera UVM release into vendor/accellera/uvm-core/."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--release",
        metavar="NAME",
        help="the Accellera release name, such as 2020-3.2; default the newest one listed",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="compare upstream/ with the archive release.toml records instead of rewriting it",
    )
    args = parser.parse_args(argv)
    where = PACKAGE.relative_to(REPO_ROOT).as_posix()
    try:
        if args.check:
            problems = check(PACKAGE)
            for line in problems:
                print(f"{where}/upstream: {line}", file=sys.stderr)
            if problems:
                return 1
            print(f"{where}/upstream: matches UVM {read_record(PACKAGE)['release']}")
            return 0
        release, count = update(PACKAGE, args.release)
    except UpdateError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    print(f"{where}/upstream: UVM {release.name}, {count} files from {release.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
