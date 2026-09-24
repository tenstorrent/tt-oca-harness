#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Trim the published dashboard data down to what the web pages render.

A series is one block as run by one framework on one simulator, named by
``flow``, ``framework`` and ``tool`` together. Every entry below carries all
three, so the page can tell one series from another.

The ``combine`` subcommand collects what several publishers published into the
one file the rest of the pipeline reads, concatenating ``dut_status``,
``results`` and ``points`` and keeping the newest ``generated_at``.

The ``summary`` subcommand reads a published summary and keeps only:

    {
      "generated_at": str,
      "dut_status":   [{"flow": str, "framework": str, "tool": str,
                        "tests_total": int, "pass_rate": float,
                        "coverage_total_percent": float}],
      "results":      [{"flow": str, "framework": str, "tool": str,
                        "coverage": {"effective_metrics": {...}}}]
    }

With ``--tests-out``, a second file for the block pages:

    {
      "generated_at": str,
      "results": [{"flow": str, "framework": str, "tool": str,
                   "tests": [{"name": str, "status": str, "category": str,
                              "seed": int, "duration_sec": float,
                              "stage": str}]}]
    }

The ``history`` subcommand reads a published history and writes the series for
the trends page:

    {
      "points": [{"generated_at": str, "test_pass_rate": float,
                  "flow_pass_rate": float, "failed_tests": int,
                  "flaky_tests": int,
                  "per_dut": [{"flow": str, "framework": str, "tool": str,
                               "coverage_status": str,
                               "effective_metrics": {...}}]}]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Every tuple below is exactly what dashboard.adoc reads. Adding a column to
# the page means adding its field here too, or the cell renders as n/a.
SUMMARY_KEYS: tuple[str, ...] = ("generated_at",)

# The fields that together name one series.
IDENTITY_KEYS: tuple[str, ...] = ("flow", "framework", "tool")

DUT_KEYS: tuple[str, ...] = IDENTITY_KEYS + (
    "tests_total",
    "pass_rate",
    "coverage_total_percent",
)

# dut_status[] flattens coverage to a single total_percent, so the per-metric
# breakdown (line/toggle/assertion/functional) only exists on results[].
RESULT_KEYS: tuple[str, ...] = IDENTITY_KEYS
COVERAGE_KEYS: tuple[str, ...] = ("effective_metrics",)

# Per-test fields for the block pages, written to a separate file.
TEST_KEYS: tuple[str, ...] = ("name", "status", "category", "seed", "duration_sec", "stage")

# Per-point fields for the trends page.
HISTORY_POINT_KEYS: tuple[str, ...] = (
    "generated_at",
    "test_pass_rate",
    "flow_pass_rate",
    "failed_tests",
    "flaky_tests",
)
HISTORY_DUT_KEYS: tuple[str, ...] = IDENTITY_KEYS + ("coverage_status", "effective_metrics")


def trim_test(test: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce one tests_detail[] entry to the columns a block page shows.

    Args:
        test: A single entry from a result's tests_detail list

    Returns:
        The entry with only TEST_KEYS. Absent fields are left out rather than
        filled in, so the page decides how to render them
    """
    return {key: test[key] for key in TEST_KEYS if key in test}


def trim_history_point(point: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce one history point to the fields plotted by the trends page.

    Args:
        point: A single entry from the published history's points list

    Returns:
        The point with only HISTORY_POINT_KEYS, and a per_dut list holding
        only HISTORY_DUT_KEYS
    """
    trimmed = {key: point[key] for key in HISTORY_POINT_KEYS if key in point}
    duts = point.get("per_dut")
    if isinstance(duts, list):
        trimmed["per_dut"] = [
            {key: dut[key] for key in HISTORY_DUT_KEYS if key in dut}
            for dut in duts
            if isinstance(dut, dict)
        ]
    return trimmed


def trim_result(result: dict[str, Any]) -> dict[str, Any]:
    """
    Reduce one results[] entry to its flow name and coverage metrics.

    Args:
        result: A single entry from the published summary's results list

    Returns:
        The entry with only RESULT_KEYS, plus a coverage object holding only
        COVERAGE_KEYS. Coverage is omitted when the entry carries none
    """
    trimmed = {key: result[key] for key in RESULT_KEYS if key in result}
    coverage = result.get("coverage")
    if isinstance(coverage, dict):
        trimmed["coverage"] = {key: coverage[key] for key in COVERAGE_KEYS if key in coverage}
    return trimmed


def moment(raw: Any) -> datetime:
    """
    Read a published timestamp.

    Publishers need not agree on a UTC offset, so the values are compared as
    moments rather than as the strings they arrive in.

    Args:
        raw: The published value, of any type

    Returns:
        The timestamp, or the earliest representable one where it is absent or
        unreadable, so a usable timestamp always wins
    """
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def read_json(source: Path) -> Any:
    """
    Read a JSON file, reporting an unreadable or malformed file on stderr.

    Args:
        source: Path to the file to read

    Returns:
        The decoded document, or None if it could not be read
    """
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"error: cannot read {source}: {error}", file=sys.stderr)
        return None


def write_json(output: Path, document: dict[str, Any]) -> None:
    """
    Write a JSON document, creating the parent directory if needed.

    Args:
        output: Path to write
        document: The document to serialise
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def trim_summary(args: argparse.Namespace) -> int:
    """
    Read the published summary and write the trimmed file, plus the per-flow
    test detail when --tests-out is given.

    Args:
        args: Parsed arguments carrying source, output and tests_out

    Returns:
        0 on success, 1 when the source is unreadable or is not a JSON object
    """
    summary = read_json(args.source)
    if summary is None:
        return 1

    if not isinstance(summary, dict):
        print(f"error: {args.source} is not a JSON object", file=sys.stderr)
        return 1

    trimmed: dict[str, Any] = {key: summary[key] for key in SUMMARY_KEYS if key in summary}

    # A summary with no flows is passed through as an empty list: the page
    # declares its own rows, so every block renders as n/a rather than the
    # table vanishing.
    duts = summary.get("dut_status")
    if isinstance(duts, list):
        trimmed["dut_status"] = [
            {key: dut[key] for key in DUT_KEYS if key in dut}
            for dut in duts
            if isinstance(dut, dict)
        ]

    results = summary.get("results")
    if isinstance(results, list):
        trimmed["results"] = [trim_result(result) for result in results if isinstance(result, dict)]

    write_json(args.output, trimmed)

    if args.tests_out:
        detailed: list[dict[str, Any]] = []
        for result in summary.get("results") or []:
            if not isinstance(result, dict) or not result.get("flow"):
                continue
            tests = result.get("tests_detail")
            if not isinstance(tests, list):
                continue
            entry = {key: result[key] for key in IDENTITY_KEYS if key in result}
            entry["tests"] = [trim_test(test) for test in tests if isinstance(test, dict)]
            detailed.append(entry)
        detail: dict[str, Any] = {
            "generated_at": summary.get("generated_at"),
            "results": detailed,
        }
        write_json(args.tests_out, detail)

    return 0


def trim_history(args: argparse.Namespace) -> int:
    """
    Read the published history and write the trimmed file for the trends page.

    Args:
        args: Parsed arguments carrying source and output

    Returns:
        0 on success, 1 when the source is unreadable
    """
    history = read_json(args.source)
    if history is None:
        return 1

    points = history.get("points") if isinstance(history, dict) else None
    trend: dict[str, Any] = {
        "points": [trim_history_point(point) for point in points or [] if isinstance(point, dict)]
    }
    write_json(args.output, trend)

    return 0


def combine_published(args: argparse.Namespace) -> int:
    """
    Collect what several publishers published into one document.

    Each publisher keeps its own directory on the data branch and reports one
    series, so the page reads one file holding all of them. Every entry carries
    the flow, framework and tool naming it, so no entry is altered or folded
    into another.

    Args:
        args: Parsed arguments carrying sources and output

    Returns:
        0 on success, 1 when a source is unreadable or is not a JSON object
    """
    collected: dict[str, Any] = {}
    for source in args.sources:
        document = read_json(source)
        if document is None:
            return 1
        if not isinstance(document, dict):
            print(f"error: {source} is not a JSON object", file=sys.stderr)
            return 1
        # Each list simply grows by what this publisher reported.
        for key in ("dut_status", "results", "points"):
            entries = document.get(key)
            if isinstance(entries, list):
                collected.setdefault(key, []).extend(entries)
        # The whole file is as recent as its most recent publisher.
        stamp = moment(document.get("generated_at"))
        if stamp > moment(collected.get("generated_at")):
            collected["generated_at"] = document["generated_at"]

    # The trends page plots points in order, whichever publisher they came from.
    points = collected.get("points")
    if isinstance(points, list):
        points.sort(key=lambda point: moment(point.get("generated_at")))

    write_json(args.output, collected)
    return 0


def main() -> int:
    """
    Parse arguments and dispatch to the selected subcommand.

    Returns:
        0 on success, 1 when an input is unreadable or malformed
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subcommands = parser.add_subparsers(dest="subcommand", required=True)

    summary = subcommands.add_parser("summary", help="trim the published summary")
    summary.add_argument("source", type=Path, help="published summary.json")
    summary.add_argument("output", type=Path, help="trimmed file to write")
    summary.add_argument(
        "--tests-out",
        type=Path,
        help="optional per-flow test detail for the block pages",
    )

    history = subcommands.add_parser("history", help="trim the published history")
    history.add_argument("source", type=Path, help="published history.json")
    history.add_argument("output", type=Path, help="trend series to write")

    combine = subcommands.add_parser(
        "combine", help="collect what several publishers published into one file"
    )
    combine.add_argument("output", type=Path, help="collected file to write")
    combine.add_argument("sources", type=Path, nargs="+", help="published files to collect")

    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "summary": trim_summary,
        "history": trim_history,
        "combine": combine_published,
    }

    args = parser.parse_args()
    return handlers[args.subcommand](args)


if __name__ == "__main__":
    raise SystemExit(main())
