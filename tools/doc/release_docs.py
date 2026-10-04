# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Frozen per-release documentation snapshots for the GitHub Pages site.

The site root always carries the documentation built from ``main``. Each
published GitHub release that carries a ``docs-<tag>.tar.gz`` asset is served
beside it under ``<tag>/``, and ``versions.json`` at the root lists them for
the header version menu.

    release_docs.py stamp <tag>                  set every book's Antora version
    release_docs.py pack <site-dir> <tarball>    archive a built site
    release_docs.py restore <site-dir>           unpack every release snapshot
                                                 into <site-dir>/<tag>/ and write
                                                 <site-dir>/versions.json

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
VERSION_LINE = re.compile(r"^version: latest$", re.MULTILINE)
# A tag names a directory at the site root, beside the Antora components.
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def asset_name(tag: str) -> str:
    return f"docs-{tag}.tar.gz"


def version_of(tag: str) -> str:
    return tag[1:] if re.match(r"^v[0-9]", tag) else tag


def check_tag(tag: str) -> str:
    if not TAG.match(tag) or version_of(tag) == LATEST:
        raise SystemExit(f"error: {tag!r} cannot name a documentation snapshot")
    return tag


def stamp(tag: str, doc_dir: Path) -> list[Path]:
    """Replace ``version: latest`` in every book's antora.yml."""
    version = version_of(check_tag(tag))
    books = sorted(doc_dir.glob("*/antora.yml"))
    if not books:
        raise SystemExit(f"error: no antora.yml under {doc_dir}")
    for book in books:
        text = book.read_text()
        if not VERSION_LINE.search(text):
            raise SystemExit(f"error: {book} does not declare 'version: latest'")
        book.write_text(VERSION_LINE.sub(f"version: '{version}'", text, count=1))
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
    """Published releases, newest first, with their asset names."""
    tags = json.loads(
        gh("release", "list", "--exclude-drafts", "--limit", "1000", "--json", "tagName")
    )
    found = []
    for entry in tags:
        tag = entry["tagName"]
        assets = json.loads(gh("release", "view", tag, "--json", "assets"))["assets"]
        found.append({"tag": tag, "assets": [a["name"] for a in assets]})
    return found


def restore(site: Path, available: list[dict]) -> list[dict]:
    versions = [{"version": LATEST, "path": ""}]
    for release in available:
        tag = release["tag"]
        asset = asset_name(tag)
        if asset not in release["assets"]:
            print(f"note: release {tag} carries no {asset}; not published")
            continue
        check_tag(tag)
        dest = site / tag
        shutil.rmtree(dest, ignore_errors=True)
        with tempfile.TemporaryDirectory() as tmp:
            gh("release", "download", tag, "--pattern", asset, "--dir", tmp)
            dest.mkdir()
            with tarfile.open(Path(tmp) / asset) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(dest, filter="data")
                else:
                    tar.extractall(dest)
        versions.append({"version": version_of(tag), "path": f"{tag}/"})
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
    p = sub.add_parser("pack")
    p.add_argument("site", type=Path)
    p.add_argument("tarball", type=Path)
    p = sub.add_parser("restore")
    p.add_argument("site", type=Path)
    args = parser.parse_args(argv)

    if args.command == "stamp":
        for book in stamp(args.tag, args.doc_dir):
            print(f"Stamped {book.relative_to(args.doc_dir)} as {version_of(args.tag)}")
    elif args.command == "pack":
        pack(args.site, args.tarball)
    else:
        if shutil.which("gh") is None:
            raise SystemExit("error: restoring release snapshots needs the GitHub CLI (gh)")
        restore(args.site, releases())
    return 0


if __name__ == "__main__":
    sys.exit(main())
