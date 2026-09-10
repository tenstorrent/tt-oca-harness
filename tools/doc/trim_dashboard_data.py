#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Trim the published dashboard summary down to what the web page renders.

Reads ``latest/summary.json`` from the ``dv-dashboard-data`` branch and keeps
only the following:

    {
      "generated_at": str,
      "dut_status":   [{"flow": str, "tests_total": int,
                        "pass_rate": float}],
      "results":      [{"flow": str,
                        "coverage": {"effective_metrics": {...}}}]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Every tuple below is exactly what dashboard.adoc reads. Adding a column to
# the page means adding its field here too, or the cell renders as n/a.
SUMMARY_KEYS: tuple[str, ...] = ("generated_at",)
DUT_KEYS: tuple[str, ...] = ("flow", "tests_total", "pass_rate")

# dut_status[] flattens coverage to a single total_percent, so the per-metric
# breakdown (line/toggle/assertion/functional) only exists on results[].
RESULT_KEYS: tuple[str, ...] = ("flow",)
COVERAGE_KEYS: tuple[str, ...] = ("effective_metrics",)


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


def main() -> int:
    """
    Read the published summary and write the trimmed file.

    Returns:
        0 on success, 1 when the source is unreadable or is not a JSON object
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", type=Path, help="published summary.json")
    parser.add_argument("output", type=Path, help="trimmed file to write")
    args = parser.parse_args()

    try:
        summary = json.loads(args.source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"error: cannot read {args.source}: {error}", file=sys.stderr)
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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(trimmed, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
