#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Aggregate per-test outcomes across the published run archives.

Reads the gzipped per-run records under ``data/runs/`` on the
``dv-dashboard-data`` branch and writes one small file for the test-history
page::

    {
      "series": [{"flow": str, "framework": str, "tool": str,
                  "runs":  [{"date": str, "id": str}],
                  "tests": {"<name>": [{"pass": int, "total": int,
                                        "seeds": [{"seed": int,
                                                   "reason": str}]} | None]}}]
    }

A block verified by more than one framework or simulator reports once per
combination, so all three name a series. Each carries its own ``runs``, oldest
first, because series run on their own cadences. Each test's list is the same
length as that series' runs, one cell per run, counting the seeds that passed
out of the seeds that ran:

    {"pass": 3, "total": 3}   every seed passed
    {"pass": 1, "total": 3}   mixed -- the run was flaky for this test
    {"pass": 0, "total": 3}   every seed failed
    null                      the test did not run; the regression ended
                              before reaching it

Every cell carries ``seeds``, one entry per seed in the order it ran, and a seed
that did not pass also carries the explanation it gave.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PASS = "PASS"

# The fields that together name one series, matching trim_dashboard_data.py.
IDENTITY_KEYS = ("flow", "framework", "tool")


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


def records(archive: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The per-run records an archive holds.

    An archive is either one run's record, carrying its tests at the top level,
    or a summary wrapping one record per DUT under ``results``.

    Args:
        archive: A parsed archive

    Returns:
        Every record it holds, in the order published
    """
    # One record.
    if isinstance(archive.get("tests_detail"), list):
        return [archive]
    # A summary.
    results = archive.get("results")
    return (
        [record for record in results if isinstance(record, dict)]
        if isinstance(results, list)
        else []
    )


def tally(record: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """
    Collect the seeds each test ran in one run.

    Args:
        record: A parsed archived run record

    Returns:
        Mapping of test name to its seeds in the order they ran, each carrying
        a reason only where the seed did not pass
    """
    seeds: dict[str, list[dict[str, Any]]] = {}
    for test in record.get("tests_detail") or []:
        if not isinstance(test, dict) or not test.get("name"):
            continue
        entry: dict[str, Any] = {"seed": test.get("seed")}
        if test.get("status") != PASS:
            entry["reason"] = str(test.get("reason") or test.get("status") or "")
        seeds.setdefault(test["name"], []).append(entry)
    return seeds


def run_id(path: str) -> str:
    """
    CI run identifier an archive came from.

    Archives are named ``<date>-run<id>.result.json.gz``.

    Args:
        path: Path to the archive within the data branch

    Returns:
        The identifier, or an empty string when the name does not carry one
    """
    match = re.search(r"-run(\d+)\.", Path(path).name)
    return match.group(1) if match else ""


def cell(seeds: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build one grid cell from a test's seeds.

    Args:
        seeds: The seeds one test ran in one run, in the order they ran

    Returns:
        The cell, counting the seeds that passed out of those that ran
    """
    return {
        "pass": sum(1 for seed in seeds if "reason" not in seed),
        "total": len(seeds),
        "seeds": seeds,
    }


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
    parser.add_argument(
        "--runs-dir",
        dest="runs_dirs",
        action="append",
        default=None,
        help="directory of run archives within the ref, e.g. vcs/dtp_uvm/data/runs/; "
        "repeat to read several publishers",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="keep only the newest N archives from each runs directory",
    )
    args = parser.parse_args()

    entries: list[tuple[datetime, str, dict[str, Any]]] = []
    for runs_dir in args.runs_dirs or ["data/runs/"]:
        paths = archive_paths(args.ref, runs_dir)
        # An archive is named by publish date, so the window is chosen before
        # any is read; the record's own timestamp then orders what is kept.
        if args.limit > 0:
            paths = sorted(paths)[-args.limit :]

        found: list[tuple[datetime, str, dict[str, Any]]] = []
        for path in paths:
            record = read_archive(args.ref, path)
            if record is None:
                print(f"warning: skipping unreadable {path}", file=sys.stderr)
                continue
            found.append((run_stamp(record, path), path, record))
        entries.extend(found)

    entries.sort(key=lambda entry: entry[0])

    # Series need not share a cadence, so each carries its own run axis rather
    # than a common one.
    runs: dict[tuple[str, ...], list[dict[str, str]]] = {}
    counts: dict[tuple[str, ...], list[dict[str, list[dict[str, Any]]]]] = {}
    for stamp, path, archive in entries:
        for record in records(archive):
            if not record.get("flow"):
                continue
            key = tuple(str(record.get(field) or "") for field in IDENTITY_KEYS)
            runs.setdefault(key, []).append({"date": stamp.date().isoformat(), "id": run_id(path)})
            counts.setdefault(key, []).append(tally(record))

    series: list[dict[str, Any]] = []
    for key in sorted(runs):
        # A test missing from a run still occupies a column, so its cell reads
        # as "did not run" rather than shifting the series.
        names = sorted({name for run in counts[key] for name in run})
        entry: dict[str, Any] = dict(zip(IDENTITY_KEYS, key))
        entry["runs"] = runs[key]
        entry["tests"] = {
            name: [cell(run[name]) if name in run else None for run in counts[key]]
            for name in names
        }
        series.append(entry)

    # Written compact rather than indented: it is machine-read only.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"series": series}, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
