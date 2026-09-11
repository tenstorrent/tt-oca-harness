#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Aggregate per-test outcomes across the published run archives.

Reads the gzipped per-run records under ``data/runs/`` on the
``dv-dashboard-data`` branch and writes one small file for the test-history
page::

    {
      "runs":  [str],
      "flows": {"<flow>": {"<name>": [{"pass": int, "total": int} | None]}}
    }

``runs`` holds one date per archive, oldest first. Each test's list is the same
length, one cell per run, counting the seeds that passed out of the seeds that
ran:

    {"pass": 3, "total": 3}   every seed passed
    {"pass": 1, "total": 3}   mixed -- the run was flaky for this test
    {"pass": 0, "total": 3}   every seed failed
    null                      the test did not run; the regression ended
                              before reaching it
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PASS = "PASS"


def archive_paths(ref: str, prefix: str) -> list[str]:
    """
    List the per-run archives on a git ref, oldest first.

    Args:
        ref: Git ref carrying the data branch
        prefix: Path prefix within that ref holding the archives

    Returns:
        Sorted archive paths; empty when the ref or prefix does not exist
    """
    try:
        listing = subprocess.check_output(
            [
                "git",
                "--literal-pathspecs",
                "ls-tree",
                "--name-only",
                "--end-of-options",
                ref,
                "--",
                prefix,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    return sorted(line for line in listing.split() if line.endswith(".gz"))


def read_archive(ref: str, path: str) -> dict[str, Any] | None:
    """
    Decompress and parse one archived run record.

    Args:
        ref: Git ref carrying the data branch
        path: Path to the gzipped record within that ref

    Returns:
        The parsed record, or None when it cannot be read
    """
    try:
        raw = subprocess.run(
            ["git", "show", "--end-of-options", f"{ref}:{path}"],
            capture_output=True,
            check=True,
        ).stdout
        record = json.loads(gzip.decompress(raw))
    except (subprocess.CalledProcessError, OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def tally(record: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """
    Count passing and total seeds per test name in one run.

    Args:
        record: A parsed archived run record

    Returns:
        Mapping of test name to (passing seeds, total seeds)
    """
    counts: dict[str, tuple[int, int]] = {}
    for test in record.get("tests_detail") or []:
        if not isinstance(test, dict) or not test.get("name"):
            continue
        passed, total = counts.get(test["name"], (0, 0))
        counts[test["name"]] = (passed + (test.get("status") == PASS), total + 1)
    return counts


def run_stamp(record: dict[str, Any], path: str) -> datetime:
    """
    When a run happened.

    An archive is named by the time its result was published, which can fall on
    the day after the run it describes. The record carries the run's own
    timestamp, so that is preferred and the publish date is only a fallback.

    Args:
        record: A parsed archived run record
        path: Path the record was read from

    Returns:
        A timezone-aware timestamp, assuming UTC where none is given
    """
    meta = record.get("run_metadata") or {}
    candidates = (meta.get("generated_at"), record.get("generated_at"), Path(path).name[:10])
    for raw in candidates:
        if not isinstance(raw, str) or not raw:
            continue
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            continue
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def main() -> int:
    """
    Aggregate the archives on a ref and write the test-history file.

    Returns:
        0 on success, including when the ref holds no archives
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("output", type=Path, help="aggregate file to write")
    parser.add_argument("--ref", default="origin/dv-dashboard-data", help="git ref to read")
    parser.add_argument("--prefix", default="data/runs/", help="archive path prefix")
    parser.add_argument("--limit", type=int, default=0, help="keep only the newest N runs")
    args = parser.parse_args()

    entries: list[tuple[datetime, dict[str, Any]]] = []
    for path in archive_paths(args.ref, args.prefix):
        record = read_archive(args.ref, path)
        if record is None:
            print(f"warning: skipping unreadable {path}", file=sys.stderr)
            continue
        entries.append((run_stamp(record, path), record))

    entries.sort(key=lambda entry: entry[0])
    if args.limit > 0:
        entries = entries[-args.limit :]

    runs: list[str] = []
    per_run: list[tuple[str, dict[str, tuple[int, int]]]] = []
    for stamp, record in entries:
        runs.append(stamp.date().isoformat())
        per_run.append((str(record.get("flow") or ""), tally(record)))

    # A run that published nothing for a flow still occupies a column, so an
    # absent cell reads as "did not run" rather than shifting the series.
    flows: dict[str, dict[str, list[dict[str, int] | None]]] = {}
    for flow in sorted({flow for flow, _ in per_run if flow}):
        names = sorted(
            {name for run_flow, counts in per_run if run_flow == flow for name in counts}
        )
        flows[flow] = {
            name: [
                {"pass": counts[name][0], "total": counts[name][1]}
                if run_flow == flow and name in counts
                else None
                for run_flow, counts in per_run
            ]
            for name in names
        }

    # Written compact rather than indented: it is machine-read only.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"runs": runs, "flows": flows}, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
