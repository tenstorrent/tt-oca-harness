#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Classify a CI diff as documentation-only or heavy.

Documentation-only means every changed path is under ``doc/``, an Antora
playbook, or a documentation suffix (``.md``, ``.adoc``, images). Anything
else is heavy: sim, slang, and the nonfree GitLab child must run.

Manual GitLab (web) and scheduled pipelines are always heavy; the caller
decides that before invoking this script.

Exit status for ``--is-docs-only`` is 0 when the diff is documentation-only
and 1 when it is heavy or cannot be classified.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DOCS_SUFFIXES = frozenset(
    {".md", ".adoc", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
)

# Returned when the diff cannot be listed. Not a docs path, so the run is heavy.
UNCLASSIFIED = "(unclassified)"


def is_docs_path(path: str) -> bool:
    """Return True when *path* is documentation collateral."""
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized == "doc" or normalized.startswith("doc/"):
        return True
    name = Path(normalized).name
    if name == "antora-playbook.yml" or (
        name.startswith("antora-") and name.endswith("-playbook.yml")
    ):
        return True
    return Path(normalized).suffix.lower() in DOCS_SUFFIXES


def parse_name_status(raw: str) -> list[str]:
    """Parse ``git diff --name-status -z`` output into every involved path."""
    parts = [part for part in raw.split("\0") if part]
    paths: list[str] = []
    i = 0
    while i < len(parts):
        status = parts[i]
        i += 1
        if i >= len(parts):
            break
        if status.startswith(("R", "C")):
            paths.append(parts[i])
            i += 1
            if i < len(parts):
                paths.append(parts[i])
                i += 1
            continue
        paths.append(parts[i])
        i += 1
    return paths


def docs_only(paths: list[str]) -> bool:
    """Return True when *paths* is non-empty and every path is documentation."""
    if not paths:
        return False
    return all(is_docs_path(path) for path in paths)


def _run_git(args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return completed.stdout


def _fetch(ref: str) -> bool:
    remote_ref = ref.removeprefix("origin/")
    return _run_git(["fetch", "--depth=1", "origin", remote_ref]) is not None


def _diff(rev_range: str) -> list[str] | None:
    raw = _run_git(["diff", "--name-status", "-z", rev_range])
    if raw is None:
        return None
    return parse_name_status(raw)


def _github_before_sha() -> str:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path:
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        before = payload.get("before")
        if isinstance(before, str):
            return before
    return os.environ.get("GITHUB_EVENT_BEFORE", "")


def _nonzero_sha(sha: str) -> bool:
    return bool(sha) and set(sha) != {"0"}


def changed_files() -> list[str]:
    """List paths in the CI event's diff, or ``[UNCLASSIFIED]`` on failure."""
    event = os.environ.get("GITHUB_EVENT_NAME")
    if event == "pull_request":
        base = os.environ.get("GITHUB_BASE_REF") or "main"
        _fetch(base)
        paths = _diff(f"origin/{base}...HEAD")
        return paths if paths is not None else [UNCLASSIFIED]
    if event == "push":
        ref = os.environ.get("GITHUB_REF_NAME") or ""
        if ref == "main":
            before = _github_before_sha()
            if _nonzero_sha(before):
                paths = _diff(f"{before}...HEAD")
                return paths if paths is not None else [UNCLASSIFIED]
        _fetch("main")
        paths = _diff("origin/main...HEAD")
        return paths if paths is not None else [UNCLASSIFIED]

    source = os.environ.get("CI_PIPELINE_SOURCE")
    if source == "merge_request_event":
        base = os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA", "")
        if _nonzero_sha(base):
            paths = _diff(f"{base}...HEAD")
            return paths if paths is not None else [UNCLASSIFIED]
        target = os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") or "main"
        _fetch(target)
        paths = _diff(f"origin/{target}...HEAD")
        return paths if paths is not None else [UNCLASSIFIED]
    if source == "external_pull_request_event":
        target = os.environ.get("CI_EXTERNAL_PULL_REQUEST_TARGET_BRANCH_NAME") or "main"
        _fetch(target)
        paths = _diff(f"origin/{target}...HEAD")
        return paths if paths is not None else [UNCLASSIFIED]
    if source == "push":
        branch = os.environ.get("CI_COMMIT_BRANCH") or ""
        if branch == "main":
            before = os.environ.get("CI_COMMIT_BEFORE_SHA", "")
            sha = os.environ.get("CI_COMMIT_SHA", "HEAD")
            if _nonzero_sha(before):
                paths = _diff(f"{before}...{sha}")
                return paths if paths is not None else [UNCLASSIFIED]
        _fetch("main")
        paths = _diff("origin/main...HEAD")
        return paths if paths is not None else [UNCLASSIFIED]

    return [UNCLASSIFIED]


def self_test() -> None:
    assert is_docs_path("README.md")
    assert is_docs_path("hw/sys/dtp/doc/jtag.adoc")
    assert is_docs_path("doc/trm/src/index.adoc")
    assert is_docs_path("doc/trm/dist/ocah-trm.pdf")
    assert is_docs_path("antora-playbook.yml")
    assert is_docs_path("antora-combined-playbook.yml")
    assert is_docs_path("hw/ip/uart/doc/diagram.svg")
    assert not is_docs_path("hw/sys/smc/rtl/smc.sv")
    assert not is_docs_path(".gitlab-ci.yml")
    assert not is_docs_path("scripts/docker-run.sh")
    assert not is_docs_path("Bender.yml")
    assert not is_docs_path(UNCLASSIFIED)

    renamed = parse_name_status("R100\0hw/sys/smc/rtl/old.sv\0README.md\0")
    assert renamed == ["hw/sys/smc/rtl/old.sv", "README.md"]
    assert not docs_only(renamed)
    assert docs_only(["README.md", "doc/contributing/src/index.adoc"])
    assert not docs_only([])
    assert not docs_only([UNCLASSIFIED])
    print("classify_diff self-test ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--is-docs-only",
        action="store_true",
        help="exit 0 if documentation-only, 1 if heavy",
    )
    mode.add_argument(
        "--github-output",
        action="store_true",
        help="print heavy=true|false for GITHUB_OUTPUT",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0

    paths = changed_files()
    only_docs = docs_only(paths)
    print(f"changed: {', '.join(paths) or '(none)'}", file=sys.stderr)
    print(f"docs_only={str(only_docs).lower()}", file=sys.stderr)

    if args.github_output:
        print(f"heavy={str(not only_docs).lower()}")
        return 0
    if args.is_docs_only:
        return 0 if only_docs else 1
    print("docs_only" if only_docs else "heavy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
