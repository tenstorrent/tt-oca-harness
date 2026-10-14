# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Unified CLI for OCAH static dashboard utilities."""

from __future__ import annotations

import argparse

from . import collect_results, gen_dashboard, gen_report, publish_reports, sanitize


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_dashboard.py",
        description="Collect, render, and publish static OCAH DV/FV dashboard reports.",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    collect = subparsers.add_parser("collect", help="collect one DUT result")
    collect.add_argument("--dut", required=True)
    collect.add_argument(
        "--framework",
        help="framework view to resolve (e.g. uvm); default: the DUT's default_framework",
    )
    collect.add_argument("--run-dir")
    collect.add_argument("--output")
    collect.add_argument(
        "--all-attempts",
        action="store_true",
        help="keep every attempt of a retried leaf in tests_detail (default: its final attempt)",
    )

    report = subparsers.add_parser("report", help="generate one per-flow HTML report")
    report.add_argument("--result", required=True)
    report.add_argument("--html-out", required=True)
    report.add_argument("--json-out")

    dash = subparsers.add_parser("dashboard", help="generate top-level dashboard")
    dash.add_argument("--results", nargs="+", required=True)
    dash.add_argument("--html-out")
    dash.add_argument("--summary-out", required=True)
    dash.add_argument("--history-in")
    dash.add_argument("--history-out")

    publish = subparsers.add_parser("publish", help="publish generated static reports")
    publish.add_argument("--source", required=True)
    publish.add_argument("--publish-root", required=True)
    publish.add_argument("--name", default="dashboard")
    publish.add_argument("--timestamp")

    clean = subparsers.add_parser(
        "sanitize", help="rewrite host-specific paths and hosts in published JSON files"
    )
    clean.add_argument(
        "--check", action="store_true", help="rewrite nothing; exit 1 when any file would change"
    )
    clean.add_argument(
        "--root",
        action="append",
        default=[],
        help="another checkout root whose paths become repository-relative (repeatable)",
    )
    clean.add_argument("files", nargs="+", help="JSON or gzipped JSON files to rewrite in place")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.cmd == "collect":
        return collect_results.main(
            [
                "--dut",
                args.dut,
                *(["--framework", args.framework] if args.framework else []),
                *(["--run-dir", args.run_dir] if args.run_dir else []),
                *(["--output", args.output] if args.output else []),
                *(["--all-attempts"] if args.all_attempts else []),
            ]
        )
    if args.cmd == "report":
        return gen_report.main(
            [
                "--result",
                args.result,
                "--html-out",
                args.html_out,
                *(["--json-out", args.json_out] if args.json_out else []),
            ]
        )
    if args.cmd == "dashboard":
        return gen_dashboard.main(
            [
                "--results",
                *args.results,
                *(["--html-out", args.html_out] if args.html_out else []),
                "--summary-out",
                args.summary_out,
                *(["--history-in", args.history_in] if args.history_in else []),
                *(["--history-out", args.history_out] if args.history_out else []),
            ]
        )
    if args.cmd == "publish":
        return publish_reports.main(
            [
                "--source",
                args.source,
                "--publish-root",
                args.publish_root,
                "--name",
                args.name,
                *(["--timestamp", args.timestamp] if args.timestamp else []),
            ]
        )
    if args.cmd == "sanitize":
        return sanitize.main(
            [
                *(["--check"] if args.check else []),
                *(f"--root={root}" for root in args.root),
                "--",
                *args.files,
            ]
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
