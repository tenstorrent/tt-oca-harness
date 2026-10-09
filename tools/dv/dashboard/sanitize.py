# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Keep host-specific paths and hosts out of published dashboard data.

Every key and string in a record, summary, or history is rewritten. A path under a checkout root
becomes repository-relative, and a path under another checkout keeps its tail from the first
top-level name Git tracks here. Any other absolute path becomes `EXTERNAL_PATH`, and a URL,
remote, or host outside GitHub becomes `EXTERNAL_URL` or `EXTERNAL_HOST`. The rewrite is
idempotent. `collect` and `dashboard` apply it to everything they write; this command applies it
to files already written:

    python3 tools/dv/run_dashboard.py sanitize [--check] [--root PATH ...] FILE ...
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

EXTERNAL_PATH = "EXTERNAL_PATH"
EXTERNAL_URL = "EXTERNAL_URL"
EXTERNAL_HOST = "EXTERNAL_HOST"

PUBLIC_HOST_SUFFIXES = ("github.com", "githubusercontent.com", "github.io")
PLACEHOLDERS = (EXTERNAL_PATH, EXTERNAL_URL, EXTERNAL_HOST)
MAX_PASSES = 8
REPO_ROOT = Path(__file__).resolve().parents[3]

_IPV4 = r"\d{1,3}(?:\.\d{1,3}){3}"
# A zone ID follows `%`, which a URL encodes as `%25`.
_ZONE = r"(?:%[\w.~%-]+)?"
_IPV6 = rf"\[[0-9A-Fa-f.]*:[0-9A-Fa-f.]*:[0-9A-Fa-f:.]*{_ZONE}\]"
# Without brackets, an IPv6 host needs `::`, so `job@10:15:22` is not one.
_BARE_IPV6 = rf"[0-9A-Fa-f.:]*::[0-9A-Fa-f.:]*{_ZONE}(?<!\.)(?![\w%:])"
_USER = r"[\w.-][\w.+-]*"
# A remote's host starts with a letter or is an IP address, so `value@100ns:` is not one.
_HOST = rf"(?:[A-Za-z][\w-]*(?:\.[\w-]+)*|{_IPV4}|{_IPV6})"
_URL_CHARACTER = r"[^\s'\"`<>()\[\]{},;]"
_URL_END = r"[^\s'\"`<>()\[\]{},;.:]"
_SCHEME = r"(?<![\w.+@-])(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://"
_NESTED_URL = re.compile(rf"{_SCHEME}(?P<netloc>[^/]*)")
_URL = re.compile(
    rf"{_SCHEME}(?P<rest>"
    rf"(?:[^\s'\"`<>()\[\]{{}},;/@]*@)?{_IPV6}(?:{_URL_CHARACTER}*{_URL_END})?"
    rf"|{_URL_CHARACTER}*{_URL_END})"
)
_SCP_REMOTE = re.compile(rf"(?<![\w.+@-]){_USER}@(?P<host>{_HOST}):(?=[\w.~-])(?!\d+@)[\w./~-]+")
_AT_IPV6 = re.compile(rf"(?<![\w.+@-]){_USER}@(?:{_IPV6}|{_BARE_IPV6})")
# After `@`, a host is an IP address, a dotted name from a letter to an all-letter last label,
# or one name after a numeric port, so `smoke@fast`, `checkout@v4`, and `pkg@1.2.3` are not.
_DOTTED_HOST = re.compile(rf"{_IPV4}|[A-Za-z][\w-]*(?:\.[\w-]+)*\.[A-Za-z]{{2,}}")
_PORT_HOST = re.compile(r"\d+@[A-Za-z][\w-]*")
# A run of name characters joined by `@` is one reference; a trailing dot ends a sentence.
_AT_RUN = re.compile(r"(?<![\w.+@-])[\w.+-]*@[\w.+@-]*(?<!\.)")
_PATH_CHARACTERS = r"(?:[\w.+%@-]|=(?!/))"
# A path starts at `/` that no word character, dot, slash, tilde, or dash precedes, or that a
# one-letter option such as `-I` or `-f` precedes. Its first component starts with a word
# character or dot, so `+/-` is not a path.
_PATH_START = r"(?:(?<![\w./~-])|(?<=(?<![\w./-])-[A-Za-z]))"


def _is_public_host(host: str) -> bool:
    host = host.lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in PUBLIC_HOST_SUFFIXES)


def _url(match: re.Match[str]) -> str:
    # A URL nested in a path runs to the end of the URL around it, so the next scheme after a
    # host starts the next nested URL. A kept URL keeps its host and a numeric port only.
    url = match.group(0)
    parts: list[str] = []
    tail = 0
    for nested in _NESTED_URL.finditer(url):
        if nested.start("netloc") == len(url):
            break
        scheme, host = nested["scheme"], nested["netloc"].rpartition("@")[2]
        name, _, port = host.partition(":")
        parts.append(url[tail : nested.start()])
        if (
            scheme.lower() not in ("http", "https")
            or not _is_public_host(name)
            or not (port == "" or port.isdigit())
        ):
            return "".join([*parts, EXTERNAL_URL])
        parts.append(f"{scheme}://{host}")
        tail = nested.end()
    return "".join([*parts, url[tail:]])


def _scp_remote(match: re.Match[str]) -> str:
    return match.group(0) if _is_public_host(match.group("host")) else EXTERNAL_URL


def _is_host_reference(left: str, right: str) -> bool:
    right = right.rstrip(".")
    return bool(left) and bool(
        right in PLACEHOLDERS
        or _DOTTED_HOST.fullmatch(right)
        or _PORT_HOST.fullmatch(f"{left}@{right}")
    )


def _at_reference(match: re.Match[str]) -> str:
    parts = match.group(0).split("@")
    hosts = [right for left, right in zip(parts, parts[1:]) if _is_host_reference(left, right)]
    return match.group(0) if all(_is_public_host(host) for host in hosts) else EXTERNAL_HOST


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
        """Return `text` with every URL, absolute path, remote, and host rewritten.

        The passes repeat until the text stops changing: a rewrite can expose a path or host
        that the earlier pass left, such as the tail of `x.sv=-f/abs/files.f`.
        """
        if "/" not in text and "@" not in text:
            return text
        for _ in range(MAX_PASSES):
            clean = self._rewrite(text)
            if clean == text:
                break
            text = clean
        return text

    def _rewrite(self, text: str) -> str:
        text = _URL.sub(_url, text)
        text = self._external_url_tail.sub(EXTERNAL_URL, text)
        text = self._absolute_path.sub(lambda match: self._path(match.group(0)), text)
        text = _SCP_REMOTE.sub(_scp_remote, text)
        text = _AT_IPV6.sub(EXTERNAL_HOST, text)
        return _AT_RUN.sub(_at_reference, text)

    def value(self, value: Any) -> Any:
        """Return a copy of a JSON value with every key and string, at any depth, rewritten.

        Raises `ValueError` when two keys of one object rewrite to the same text.
        """
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            clean: dict[Any, Any] = {}
            for key, item in value.items():
                name = self.text(key) if isinstance(key, str) else key
                if name in clean:
                    raise ValueError(f"two keys of one object rewrite to `{name}`")
                clean[name] = self.value(item)
            return clean
        if isinstance(value, list):
            return [self.value(item) for item in value]
        return value

    @cached_property
    def _word(self) -> str:
        guard = "|".join(["-", r"\.\.?/", *(re.escape(name) + "/" for name in self.anchors)])
        return rf"(?!{guard})[\w.-]+"

    @cached_property
    def _external_url_tail(self) -> re.Pattern[str]:
        # A URL ends at a space, so a spaced path inside it continues as it would after a path.
        return re.compile(
            rf"(?<![\w.+@-]){EXTERNAL_URL}(?:\x20{self._word}(?:/+{_PATH_CHARACTERS}+)+)+"
        )

    @cached_property
    def _absolute_path(self) -> re.Pattern[str]:
        # A root matches as written, spaces included. A path continues across spaces into a word
        # of letters, digits, dots, and dashes: across one space when a slash follows the word,
        # and across any spaces when the path fills a quoted span. The word is never an option,
        # `./`, `../`, or a tracked top-level name, and it holds no `+`, `=`, `%`, or `@`, so
        # `copied /a/b to c/d`, `cp /a/b hw/c`, and `simv +load=/a/b` keep their other text and
        # their other paths.
        word = self._word
        roots = "|".join(map(re.escape, self.roots)) or "(?!)"
        start = rf"{_PATH_START}(?:(?:{roots})(?!{_PATH_CHARACTERS})|/[\w.]{_PATH_CHARACTERS}*)"
        whole = rf"{start}(?:\x20+{word}|/+{_PATH_CHARACTERS}+)*/?"
        spans = [rf"(?<={quote}){whole}(?={quote})" for quote in "'\"`"]
        return re.compile(
            "|".join([*spans, rf"{start}(?:\x20{word}(?=/)|/+{_PATH_CHARACTERS}+)*/?"])
        )

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
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.suffix == ".gz":
        payload = gzip.compress(payload, mtime=0)
    path = path.resolve()
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
        except (OSError, ValueError, EOFError, RecursionError, zlib.error) as exc:
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
