#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Add commit authors and co-authors on main who are missing from CONTRIBUTORS.

Every identity in the history goes through .mailmap first, so a contributor who committed
under another name or address is matched to their existing entry rather than added twice.
Bots and AI agents are skipped.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTORS = ROOT / "CONTRIBUTORS"
OTHER_GROUP = "Other"
DOMAIN_GROUPS = {"tenstorrent.com": "Tenstorrent", "lowrisc.org": "lowRISC"}
NOT_A_PERSON = re.compile(
    r"\[bot\]|\+Copilot@users\.noreply\.github\.com>|<noreply@github\.com>"
    r"|@anthropic\.com>|@cursor\.com>|@local\.invalid>|<tenstorrent_github_bot_admin@",
    re.IGNORECASE,
)
IDENTITY = re.compile(r"^\s*(?P<name>[^<>]*?)\s*<(?P<email>[^<>\s]+)>\s*$")
TRAILER_SEP = "\x1f"


@dataclass
class Group:
    name: str
    entries: list[str] = field(default_factory=list)


def _git(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, input=stdin, capture_output=True, text=True, check=True
    ).stdout


def _email(identity: str) -> str:
    match = IDENTITY.match(identity)
    return match["email"].casefold() if match else ""


def _sort_key(entry: str) -> tuple[str, str]:
    name = IDENTITY.match(entry)["name"]
    return (name.split()[-1].casefold(), name.casefold())


def parse(text: str) -> tuple[list[str], list[Group]]:
    """Split CONTRIBUTORS into its leading comment block and its '# <organisation>' groups.

    The leading block runs up to the first blank line; after it, a comment line opens a group.
    """
    header_text, _, body = text.partition("\n\n")
    groups: list[Group] = []
    for line in body.splitlines():
        if line.startswith("#"):
            groups.append(Group(line.lstrip("#").strip()))
        elif line.strip():
            if not groups or not IDENTITY.match(line):
                raise ValueError(f"CONTRIBUTORS: not a 'Name <email>' entry: {line!r}")
            groups[-1].entries.append(line.strip())
    return header_text.splitlines(), groups


def render(header: list[str], groups: list[Group]) -> str:
    blocks = ["\n".join(header)] if header else []
    for group in groups:
        blocks.append("\n".join([f"# {group.name}", *group.entries]))
    return "\n\n".join(blocks) + "\n"


def history_identities(rev: str) -> list[str]:
    """Every author and Co-authored-by identity reachable from *rev*, oldest first."""
    log = _git(
        "log",
        "--reverse",
        f"--format=%an <%ae>{TRAILER_SEP}%(trailers:key=Co-authored-by,valueonly,separator=%x1f)",
        rev,
    )
    identities = []
    for line in log.splitlines():
        identities += [part.strip() for part in line.split(TRAILER_SEP) if part.strip()]
    return identities


def canonical(identities: list[str]) -> list[str]:
    """Map each identity through .mailmap, dropping unparsable ones and keeping first-seen order."""
    valid = list(dict.fromkeys(i for i in identities if IDENTITY.match(i)))
    if not valid:
        return []
    mapped = _git("check-mailmap", "--stdin", stdin="\n".join(valid) + "\n").splitlines()
    return list(dict.fromkeys(mapped))


def missing(groups: list[Group], identities: list[str]) -> list[str]:
    known = {_email(entry) for group in groups for entry in group.entries}
    new = []
    for identity in identities:
        if NOT_A_PERSON.search(identity) or _email(identity) in known:
            continue
        known.add(_email(identity))
        new.append(identity)
    return new


def add(groups: list[Group], identities: list[str]) -> None:
    for identity in identities:
        domain = _email(identity).rsplit("@", 1)[-1]
        name = next(
            (group for suffix, group in DOMAIN_GROUPS.items() if domain.endswith(suffix)),
            OTHER_GROUP,
        )
        group = next((g for g in groups if g.name == name), None)
        if group is None:
            group = Group(name)
            groups.append(group)
        group.entries.append(identity)
        group.entries.sort(key=_sort_key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", default="HEAD", help="history to scan (default: HEAD)")
    parser.add_argument(
        "--check", action="store_true", help="list missing contributors and fail, without writing"
    )
    args = parser.parse_args()

    header, groups = parse(CONTRIBUTORS.read_text(encoding="utf-8"))
    new = missing(groups, canonical(history_identities(args.rev)))
    for identity in new:
        print(f"missing from CONTRIBUTORS: {identity}")
    if args.check:
        return 1 if new else 0
    if new:
        add(groups, new)
        CONTRIBUTORS.write_text(render(header, groups), encoding="utf-8")
    else:
        print("CONTRIBUTORS is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
