# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Frozen per-release documentation snapshots for the GitHub Pages site.

Each release vX.Y.Z attaches its built site as docs-vX.Y.Z.tar.gz. Beside the
main build, the site serves the newest patch of each of the newest minor series
under vX.Y/ and lists them in versions.json for the header version menu.

    release_docs.py stamp <tag> | dir <tag> | pack <site> <tarball> | restore <site>
"""

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Each snapshot is a full site, and GitHub Pages caps a published site at 1 GB.
KEEP_SERIES = 2
VERSION_LINE = re.compile(r"^version: latest$", re.MULTILINE)
RELEASE = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def release(tag):
    match = RELEASE.match(tag)
    if not match:
        raise SystemExit(f"error: {tag!r} is not a release tag of the form vX.Y.Z")
    return tuple(int(part) for part in match.groups())


def site_dir(tag):
    return "v%d.%d" % release(tag)[:2]


def asset_name(tag):
    return f"docs-{tag}.tar.gz"


def stamp(tag, doc_dir):
    """Version each book by series, so patch releases keep page URLs."""
    major, minor, patch = release(tag)
    for book in sorted(doc_dir.glob("*/antora.yml")):
        text, count = VERSION_LINE.subn(
            f"version: '{major}.{minor}'\ndisplay_version: '{major}.{minor}.{patch}'",
            book.read_text(),
        )
        if count != 1:
            raise SystemExit(f"error: {book} does not declare 'version: latest'")
        book.write_text(text)


def pack(site, tarball):
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(site, arcname=".")


def releases():
    """Published full releases with their asset names."""
    jq = ".[] | select(.draft or .prerelease | not) | {tag: .tag_name, assets: [.assets[].name]}"
    out = subprocess.run(
        ["gh", "api", "repos/{owner}/{repo}/releases", "--paginate", "--jq", jq],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [json.loads(line) for line in out.splitlines()]


def select(available, keep=KEEP_SERIES):
    """Newest patch with a snapshot of each of the newest ``keep`` series."""
    chosen = {}
    candidates = [
        r["tag"]
        for r in available
        if RELEASE.match(r["tag"]) and asset_name(r["tag"]) in r["assets"]
    ]
    for tag in sorted(candidates, key=release, reverse=True):
        if len(chosen) < keep or site_dir(tag) in chosen:
            chosen.setdefault(site_dir(tag), tag)
    return list(chosen.values())


def restore(site, tags, download):
    versions = [{"version": "latest", "path": ""}]
    for tag in tags:
        dest = site / site_dir(tag)
        shutil.rmtree(dest, ignore_errors=True)
        with tempfile.TemporaryDirectory() as tmp:
            download(tag, tmp)
            with tarfile.open(Path(tmp) / asset_name(tag)) as tar:
                tar.extractall(
                    dest, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {})
                )
        versions.append({"version": "%d.%d.%d" % release(tag), "path": f"{site_dir(tag)}/"})
    (site / "versions.json").write_text(json.dumps(versions, indent=2) + "\n")
    return versions


def gh_download(tag, dest):
    subprocess.run(
        ["gh", "release", "download", tag, "--pattern", asset_name(tag), "--dir", dest], check=True
    )


COMMANDS = {
    "stamp": lambda tag: stamp(tag, ROOT / "doc"),
    "dir": lambda tag: print(site_dir(tag)),
    "pack": lambda site, tarball: pack(Path(site), Path(tarball)),
    "restore": lambda site: restore(Path(site), select(releases()), gh_download),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](*sys.argv[2:])
