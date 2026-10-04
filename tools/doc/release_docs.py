# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Frozen per-release documentation snapshots for the GitHub Pages site.

The site root always carries the documentation built from ``main``. Each
published release ``vX.Y.Z`` attaches its snapshot as ``docs-vX.Y.Z.tar.gz``.
The site serves the newest patch of each of the newest minor series under
``vX.Y/``, so a patch release replaces its predecessor in place, and lists
them in ``versions.json`` for the header version menu. Every snapshot stays
attached to its release.

    release_docs.py stamp <tag>                  set every book's Antora version
    release_docs.py dir <tag>                    print the snapshot's site directory
    release_docs.py pack <site-dir> <tarball>    archive a built site
    release_docs.py restore <site-dir>           unpack the published snapshots
                                                 and write versions.json

``restore`` reads releases through ``gh`` and needs it authenticated against
the repository (``GH_TOKEN`` in CI).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LATEST = "latest"
# Published minor series. Each snapshot is a full site and GitHub Pages caps a
# published site at 1 GB.
KEEP_SERIES = 2
VERSION_LINE = re.compile(r"^version: latest$", re.MULTILINE)
RELEASE = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def parse(tag: str) -> tuple[int, int, int] | None:
    match = RELEASE.match(tag)
    return tuple(int(part) for part in match.groups()) if match else None


def release(tag: str) -> tuple[int, int, int]:
    version = parse(tag)
    if version is None:
        raise SystemExit(f"error: {tag!r} is not a release tag of the form vX.Y.Z")
    return version


def series(tag: str) -> str:
    major, minor, _ = release(tag)
    return f"{major}.{minor}"


def display(tag: str) -> str:
    return ".".join(str(part) for part in release(tag))


def site_dir(tag: str) -> str:
    return f"v{series(tag)}"


def asset_name(tag: str) -> str:
    return f"docs-{tag}.tar.gz"


def stamp(tag: str, doc_dir: Path) -> list[Path]:
    """Version every book by its minor series, shown as the full release.

    Page URLs carry the series, so a patch release keeps every deep link.
    """
    stamped = f"version: '{series(tag)}'\ndisplay_version: '{display(tag)}'"
    books = sorted(doc_dir.glob("*/antora.yml"))
    if not books:
        raise SystemExit(f"error: no antora.yml under {doc_dir}")
    for book in books:
        text = book.read_text()
        if not VERSION_LINE.search(text):
            raise SystemExit(f"error: {book} does not declare 'version: latest'")
        book.write_text(VERSION_LINE.sub(stamped, text, count=1))
    return books


def pack(site: Path, tarball: Path) -> None:
    if not (site / "index.html").is_file():
        raise SystemExit(f"error: {site} holds no built site")
    tarball.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "w:gz") as tar:
        for entry in sorted(site.iterdir()):
            tar.add(entry, arcname=entry.name)


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def releases() -> list[dict]:
    """Published, non-prerelease releases with their asset names."""
    listed = json.loads(
        gh(
            "release",
            "list",
            "--exclude-drafts",
            "--limit",
            "1000",
            "--json",
            "tagName,isPrerelease",
        )
    )
    found = []
    for entry in listed:
        tag = entry["tagName"]
        if entry["isPrerelease"] or parse(tag) is None:
            continue
        assets = json.loads(gh("release", "view", tag, "--json", "assets"))["assets"]
        found.append({"tag": tag, "assets": [a["name"] for a in assets]})
    return found


def select(available: list[dict], keep: int) -> list[str]:
    """Newest patch carrying a snapshot of each of the newest ``keep`` series."""
    chosen: dict[str, str] = {}
    for entry in sorted(available, key=lambda e: release(e["tag"]), reverse=True):
        tag = entry["tag"]
        if asset_name(tag) not in entry["assets"]:
            print(f"note: release {tag} carries no {asset_name(tag)}")
            continue
        if series(tag) not in chosen:
            if len(chosen) == keep:
                break
            chosen[series(tag)] = tag
    return list(chosen.values())


def restore(site: Path, available: list[dict], keep: int = KEEP_SERIES) -> list[dict]:
    versions = [{"version": LATEST, "path": ""}]
    for tag in select(available, keep):
        asset = asset_name(tag)
        dest = site / site_dir(tag)
        shutil.rmtree(dest, ignore_errors=True)
        with tempfile.TemporaryDirectory() as tmp:
            gh("release", "download", tag, "--pattern", asset, "--dir", tmp)
            dest.mkdir()
            with tarfile.open(Path(tmp) / asset) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(dest, filter="data")
                else:
                    tar.extractall(dest)
        versions.append({"version": display(tag), "path": f"{site_dir(tag)}/"})
        print(f"Restored documentation snapshot {tag} into {dest}")
    (site / "versions.json").write_text(json.dumps(versions, indent=2) + "\n")
    return versions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("stamp")
    p.add_argument("tag")
    p.add_argument("--doc-dir", type=Path, default=ROOT / "doc")
    p = sub.add_parser("dir")
    p.add_argument("tag")
    p = sub.add_parser("pack")
    p.add_argument("site", type=Path)
    p.add_argument("tarball", type=Path)
    p = sub.add_parser("restore")
    p.add_argument("site", type=Path)
    p.add_argument("--keep", type=int, default=KEEP_SERIES, help="minor series to publish")
    args = parser.parse_args(argv)

    if args.command == "stamp":
        for book in stamp(args.tag, args.doc_dir):
            print(f"Stamped {book.relative_to(args.doc_dir)} as {display(args.tag)}")
    elif args.command == "dir":
        print(site_dir(args.tag))
    elif args.command == "pack":
        pack(args.site, args.tarball)
    else:
        if shutil.which("gh") is None:
            raise SystemExit("error: restoring release snapshots needs the GitHub CLI (gh)")
        restore(args.site, releases(), args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
