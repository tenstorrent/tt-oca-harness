# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Keep host-specific paths and hosts out of published dashboard data.

Every string in a record, summary, or history is rewritten. A path under a checkout root becomes
repository-relative, and a path under another checkout keeps its tail from the first top-level
name Git tracks here. Any other absolute path becomes `EXTERNAL_PATH`, and a URL, remote, or host
outside GitHub becomes `EXTERNAL_URL` or `EXTERNAL_HOST`. The rewrite is idempotent. `collect`
and `dashboard` apply it to everything they write; this command applies it to files already
written:

    python3 tools/dv/run_dashboard.py sanitize [--check] [--root PATH ...] FILE ...
"""

from __future__ import annotations

import argparse
import gzip
import json
import posixpath
import re
import shutil
import subprocess
import sys
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXTERNAL_PATH = "EXTERNAL_PATH"
EXTERNAL_URL = "EXTERNAL_URL"
EXTERNAL_HOST = "EXTERNAL_HOST"

PUBLIC_HOST_SUFFIXES = ("github.com", "githubusercontent.com", "github.io")
REPO_ROOT = Path(__file__).resolve().parents[3]

# A host starts with a letter or is an IPv4 address, so `value@100ns` and `addr@0x20` in log
# messages are not hosts.
_HOST = r"(?:[A-Za-z][\w-]*(?:\.[\w-]+)*|\d{1,3}(?:\.\d{1,3}){3})"
_HOST_NAME = re.compile(_HOST)
_URL = re.compile(
    r"(?<![\w.+-])(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://"
    r"(?P<rest>[^\s'\"`<>()\[\]{},;]*[^\s'\"`<>()\[\]{},;.:])"
)
_SCP_REMOTE = re.compile(rf"(?<![\w.+-])[\w.-]+@(?P<host>{_HOST}):(?=[\w.~-])[\w./~-]+")
_AT_REFERENCE = re.compile(r"(?<![\w.+@-])(?>[\w.-]+(?:@[\w-]+(?:\.[\w-]+)*)+)")
_PATH_CHARACTERS = r"[\w.+%=@-]"
# A path starts at `/` that no word character, dot, slash, tilde, or dash precedes, or that a
# one-letter option such as `-I` or `-f` precedes. Its first component starts with a word
# character or dot, so `+/-` is not a path.
_ABSOLUTE_PATH = re.compile(
    rf"(?:(?<![\w./~-])|(?<=(?<![\w./-])-[A-Za-z]))"
    rf"/[\w.]{_PATH_CHARACTERS}*(?:/+{_PATH_CHARACTERS}+)*/?"
)


def _is_public_host(host: str) -> bool:
    host = host.lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in PUBLIC_HOST_SUFFIXES)


def _url(match: re.Match[str]) -> str:
    scheme, rest = match.group("scheme"), match.group("rest")
    netloc, slash, path = rest.partition("/")
    host = netloc.rpartition("@")[2]
    if scheme.lower() not in ("http", "https") or not _is_public_host(host.split(":")[0]):
        return EXTERNAL_URL
    return f"{scheme}://{host}{slash}{_URL.sub(_url, path)}"


def _scp_remote(match: re.Match[str]) -> str:
    return match.group(0) if _is_public_host(match.group("host")) else EXTERNAL_URL


def _at_reference(match: re.Match[str]) -> str:
    hosts = [part for part in match.group(0).split("@")[1:] if _HOST_NAME.fullmatch(part)]
    if all(_is_public_host(host) for host in hosts):
        return match.group(0)
    return EXTERNAL_HOST


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _within(tail: str) -> str:
    return EXTERNAL_PATH if posixpath.normpath(tail).split("/")[0] == ".." else tail


@dataclass(frozen=True)
class Scrubber:
    """Rewrites strings for publication.

    `roots` are absolute checkout prefixes, longest first; a path under one is made relative to
    it. `anchors` are the repository's tracked top-level names: a path under some other prefix
    keeps its tail from the first anchor whose first two components exist under `repo_root`.
    A tail that climbs out of the checkout with `..` is not kept.
    """

    repo_root: Path
    roots: tuple[str, ...]
    anchors: frozenset[str]

    def text(self, text: str) -> str:
        """Return `text` with every URL, absolute path, remote, and host rewritten."""
        if "/" not in text and "@" not in text:
            return text
        text = _URL.sub(_url, text)
        text = _ABSOLUTE_PATH.sub(lambda match: self._path(match.group(0)), text)
        text = _SCP_REMOTE.sub(_scp_remote, text)
        return _AT_REFERENCE.sub(_at_reference, text)

    def value(self, value: Any) -> Any:
        """Return a copy of a JSON value with every string, at any depth, rewritten."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        return value

    def _path(self, path: str) -> str:
        path = re.sub("/{2,}", "/", path)
        trimmed = path.rstrip("/") or "/"
        for root in self.roots:
            if trimmed == root:
                return "."
            if trimmed.startswith(f"{root}/"):
                return _within(path[len(root) + 1 :])
        parts = trimmed.strip("/").split("/")
        for index, part in enumerate(parts):
            if part not in self.anchors:
                continue
            tail = "/".join(parts[index:])
            head = posixpath.normpath(tail).split("/")[:2]
            if head[0] != ".." and _exists(self.repo_root.joinpath(*head)):
                return tail + ("/" if path.endswith("/") else "")
        return EXTERNAL_PATH


def tracked_top_level(repo_root: Path) -> frozenset[str]:
    """Return the names Git tracks at the top of `repo_root`, or none without Git."""
    git = shutil.which("git")
    if git is None:
        return frozenset()
    listing = subprocess.run(
        [git, "-C", str(repo_root), "ls-tree", "--name-only", "-z", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        return frozenset()
    return frozenset(name for name in listing.stdout.split("\0") if name)


def checkout_scrubber(repo_root: Path, extra_roots: Iterable[Path | str] = ()) -> Scrubber:
    """Return the scrubber for `repo_root` plus `extra_roots`, each as given and resolved."""
    roots: set[str] = set()
    for root in (repo_root, *extra_roots):
        for form in (Path(root).absolute(), Path(root).resolve()):
            if form.parent != form:
                roots.add(str(form))
    return Scrubber(
        repo_root=repo_root.resolve(),
        roots=tuple(sorted(roots, key=len, reverse=True)),
        anchors=tracked_top_level(repo_root),
    )


def _read(path: Path) -> Any:
    if path.suffix == ".gz":
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        path.write_text(text, encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="rewrite nothing; exit 1 when any file would change",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="another checkout root whose paths become repository-relative (repeatable)",
    )
    parser.add_argument("files", nargs="+", help="JSON or gzipped JSON files to rewrite in place")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    scrubber = checkout_scrubber(REPO_ROOT, args.root)
    changed = failed = 0
    for name in args.files:
        path = Path(name)
        try:
            data = _read(path)
            clean = scrubber.value(data)
            if clean != data and not args.check:
                _write(path, clean)
        except (OSError, ValueError, EOFError, zlib.error) as exc:
            print(f"ERROR: {path}: {exc}", file=sys.stderr)
            failed += 1
            continue
        if clean != data:
            changed += 1
            print(f"{'Would rewrite' if args.check else 'Rewrote'}: {path}")
    if failed:
        return 2
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
