# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate a static per-flow HTML report from normalized result JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dashboard.html import COVERAGE_FIELDS, coverage_value, fmt, link, page
from dashboard.schema import read_json, write_json


def _kv_rows(data: dict, keys: list[tuple[str, str]]) -> str:
    return "\n".join(
        f"<tr><th>{fmt(label)}</th><td>{fmt(data.get(key))}</td></tr>" for key, label in keys
    )


def _test_detail_rows(result: dict) -> str:
    rows = []
    for test in result.get("tests_detail") or []:
        tags = ", ".join(test.get("tags") or [])
        junit = test.get("junit_xml", "")
        junit_cell = link(junit, "results.xml") if junit else "--"
        log = test.get("log", "")
        log_cell = link(log, "log") if log else "--"
        rows.append(
            "<tr>"
            f"<td>{fmt(test.get('name'))}</td>"
            f"<td>{fmt(test.get('category'))}</td>"
            f"<td>{fmt(tags)}</td>"
            f"<td>{fmt(test.get('target'))}</td>"
            f"<td>{fmt(test.get('seed'))}</td>"
            f"<td>{fmt(test.get('attempt'))}</td>"
            f'<td class="{fmt(test.get("status"))}">{fmt(test.get("status"))}</td>'
            f"<td>{fmt(test.get('duration_sec'))}</td>"
            f"<td>{fmt(test.get('reason'))}</td>"
            f"<td>{junit_cell}</td>"
            f"<td>{log_cell}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="11">No detailed test records collected.</td></tr>'


def _junit_rows(result: dict) -> str:
    rows = []
    for entry in result.get("junit_xml") or []:
        path = entry.get("path", "")
        rows.append(
            "<tr>"
            f"<td>{fmt(entry.get('item'))}</td>"
            f"<td>{fmt(entry.get('seed'))}</td>"
            f"<td>{fmt(entry.get('attempt'))}</td>"
            f"<td>{link(path, path) if path else '--'}</td>"
            f"<td>{fmt(entry.get('exists'))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="5">No JUnit XML artifacts collected.</td></tr>'


def _regression_failure_rows(regression: dict, key: str) -> str:
    rows = []
    for entry in regression.get(key) or []:
        log = entry.get("log", "")
        rows.append(
            "<tr>"
            f"<td>{fmt(entry.get('item'))}</td>"
            f"<td>{fmt(entry.get('seed'))}</td>"
            f'<td class="{fmt(entry.get("status") or entry.get("final_status"))}">{fmt(entry.get("status") or entry.get("final_status"))}</td>'
            f"<td>{fmt(entry.get('reason') or entry.get('flaky_reason'))}</td>"
            f"<td>{link(log, 'log') if log else '--'}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="5">None recorded.</td></tr>'


def _list_rows(values: list[str], label: str) -> str:
    return (
        "\n".join(f"<tr><td>{fmt(value)}</td></tr>" for value in values)
        or f"<tr><td>No {fmt(label)} recorded.</td></tr>"
    )


def _coverage_threshold_rows(coverage: dict) -> str:
    rows = []
    for outcome in coverage.get("policy_thresholds") or []:
        rows.append(
            "<tr>"
            f"<td>{fmt(outcome.get('id'))}</td>"
            f"<td>{fmt(outcome.get('metric_family'))}</td>"
            f"<td>{fmt(outcome.get('population'))}</td>"
            f"<td>{fmt(outcome.get('actual_percent'))}</td>"
            f"<td>{fmt(outcome.get('minimum_percent'))}</td>"
            f"<td>{fmt(outcome.get('unclassified_points'))}</td>"
            f'<td class="{"PASS" if outcome.get("met") else "FAIL"}">'
            f"{fmt(outcome.get('met'))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or (
        '<tr><td colspan="7">No coverage policy thresholds recorded.</td></tr>'
    )


def _coverage_hole_rows(coverage: dict) -> str:
    holes = coverage.get("holes_summary", {})
    details_href = coverage.get("coverage_details") or ""
    rows = []
    for hole in holes.get("samples") or []:
        issue_cells = (
            ", ".join(link(url, f"#{url.rsplit('/', 1)[-1]}") for url in hole.get("issues") or [])
            or "--"
        )
        location = hole.get("source") or hole.get("hierarchy") or ""
        if location and hole.get("line"):
            location = f"{location}:{hole.get('line')}"
        hole_id = hole.get("policy_id") or hole.get("id")
        hole_cell = link(details_href, str(hole_id)) if details_href else fmt(hole_id)
        rows.append(
            "<tr>"
            f"<td>{hole_cell}</td>"
            f"<td>{fmt(hole.get('category'))}</td>"
            f"<td>{fmt(hole.get('metric_family'))}</td>"
            f"<td>{fmt(location)}</td>"
            f'<td class="{fmt(hole.get("disposition"))}">{fmt(hole.get("disposition"))}</td>'
            f'<td class="{fmt(hole.get("status"))}">{fmt(hole.get("status"))}</td>'
            f"<td>{fmt(hole.get('owner'))}</td>"
            f"<td>{fmt(hole.get('reviewer'))}</td>"
            f"<td>{fmt(hole.get('rationale'))}</td>"
            f"<td>{issue_cells}</td>"
            "</tr>"
        )
    return "\n".join(rows) or (
        '<tr><td colspan="10">No detailed coverage holes collected.</td></tr>'
    )


def render_report(result: dict) -> str:
    tests = result.get("tests", {})
    coverage = result.get("coverage", {})
    git = result.get("git", {})
    timing = result.get("timing", {})
    artifacts = result.get("artifacts", {})
    failures = result.get("failure_buckets", [])
    status = result.get("status", "UNKNOWN")
    run_metadata = result.get("run_metadata", {})
    regression = result.get("regression", {}) if isinstance(result.get("regression"), dict) else {}
    warnings = result.get("warnings", [])

    artifact_rows = (
        "\n".join(
            f"<tr><td>{fmt(name)}</td><td>{link(path, path)}</td></tr>"
            for name, path in sorted(artifacts.items())
        )
        or '<tr><td colspan="2">No artifacts recorded.</td></tr>'
    )

    failure_rows = (
        "\n".join(
            f"<tr><td>{fmt(item.get('signature'))}</td><td>{fmt(item.get('count'))}</td></tr>"
            for item in failures
        )
        or '<tr><td colspan="2">No failure buckets recorded.</td></tr>'
    )
    run_metadata_rows = (
        _kv_rows(
            run_metadata,
            [
                ("run_dir", "Run Directory"),
                ("result_json", "Result JSON"),
                ("run_json", "Run JSON"),
                ("label", "Label"),
                ("executor", "Executor"),
                ("tool_version", "Tool Version"),
                ("generated_at", "Generated At"),
                ("dry_run", "Dry Run"),
            ],
        )
        or '<tr><td colspan="2">No run metadata collected.</td></tr>'
    )
    coverage_header = "".join(f"<th>{fmt(label)}</th>" for _, label in COVERAGE_FIELDS)
    coverage_values = "".join(
        f"<td>{fmt(coverage_value(result, name))}</td>" for name, _ in COVERAGE_FIELDS
    )

    body = f"""
<h1>{fmt(result.get("flow"))} Report</h1>
<p class="meta">Generated at {fmt(result.get("generated_at"))}</p>

<h2>Summary</h2>
<table>
  <tr><th>Status</th><td class="{fmt(status)}">{fmt(status)}</td></tr>
  <tr><th>Kind</th><td>{fmt(result.get("kind"))}</td></tr>
  <tr><th>Framework</th><td>{fmt(result.get("framework"))}</td></tr>
  <tr><th>Tool</th><td>{fmt(result.get("tool"))}</td></tr>
  <tr><th>Git Revision</th><td>{fmt(git.get("short_sha"))}</td></tr>
  <tr><th>Branch</th><td>{fmt(git.get("branch"))}</td></tr>
  <tr><th>Duration (s)</th><td>{fmt(timing.get("duration_sec"))}</td></tr>
</table>

<h2>Tests</h2>
<table>
  <tr><th>Passing</th><th>Total</th><th>Pass Rate</th><th>Coverage</th></tr>
  <tr>
    <td>{fmt(tests.get("passing"))}</td>
    <td>{fmt(tests.get("total"))}</td>
    <td>{"incomplete run" if tests.get("completed") is False else fmt(tests.get("pass_rate"))}</td>
    <td>{fmt(coverage.get("total_percent"))}</td>
  </tr>
</table>

<h2>Coverage</h2>
<table>
  <tr>{coverage_header}</tr>
  <tr>{coverage_values}</tr>
</table>

<h2>Coverage Closure Status</h2>
<table>
  <tr><th>Status</th><th>Threshold</th><th>Threshold Met</th><th>Details Available</th><th>Comparison Key</th><th>Open Holes</th><th>Accepted Holes</th><th>Unclassified Holes</th></tr>
  <tr>
    <td class="{fmt(coverage.get("status"))}">{fmt(coverage.get("status"))}</td>
    <td>{fmt(coverage.get("threshold"))}</td>
    <td>{fmt(coverage.get("threshold_met"))}</td>
    <td>{fmt(coverage.get("details_available"))}</td>
    <td>{fmt(coverage.get("comparison_key"))}</td>
    <td>{fmt((coverage.get("holes_summary") or {}).get("open"))}</td>
    <td>{fmt((coverage.get("holes_summary") or {}).get("accepted"))}</td>
    <td>{fmt((coverage.get("holes_summary") or {}).get("unclassified"))}</td>
  </tr>
</table>

<h2>Coverage Policy Thresholds</h2>
<table>
  <tr><th>Rule</th><th>Metric</th><th>Population</th><th>Actual</th><th>Minimum</th><th>Unclassified</th><th>Met</th></tr>
  {_coverage_threshold_rows(coverage)}
</table>

<h2>Coverage Holes And Waivers</h2>
<table>
  <tr><th>Hole ID</th><th>Category</th><th>Metric</th><th>Location</th><th>Disposition</th><th>Status</th><th>Owner</th><th>Reviewer</th><th>Rationale</th><th>Issues</th></tr>
  {_coverage_hole_rows(coverage)}
</table>

<h2>Artifacts</h2>
<table>
  <tr><th>Name</th><th>Path</th></tr>
  {artifact_rows}
</table>

<h2>Run Metadata</h2>
<table>
  {run_metadata_rows}
</table>

<h2>Test Details</h2>
<table>
  <tr><th>Name</th><th>Category</th><th>Tags</th><th>Target</th><th>Seed</th><th>Attempt</th><th>Status</th><th>Duration</th><th>Reason</th><th>JUnit XML</th><th>Log</th></tr>
  {_test_detail_rows(result)}
</table>

<h2>JUnit XML Artifacts</h2>
<table>
  <tr><th>Item</th><th>Seed</th><th>Attempt</th><th>Path</th><th>Exists</th></tr>
  {_junit_rows(result)}
</table>

<h2>Regression Failed Tests</h2>
<table>
  <tr><th>Item</th><th>Seed</th><th>Status</th><th>Reason</th><th>Log</th></tr>
  {_regression_failure_rows(regression, "failed_tests")}
</table>

<h2>Regression Flaky Tests</h2>
<table>
  <tr><th>Item</th><th>Seed</th><th>Status</th><th>Reason</th><th>Log</th></tr>
  {_regression_failure_rows(regression, "flaky_tests")}
</table>

<h2>Rerun Commands</h2>
<table>
  <tr><th>Command</th></tr>
  {_list_rows(regression.get("rerun_commands") or [], "rerun commands")}
</table>

<h2>Collector Warnings</h2>
<table>
  <tr><th>Warning</th></tr>
  {_list_rows(warnings, "warnings")}
</table>

<h2>Failure Buckets</h2>
<table>
  <tr><th>Signature</th><th>Count</th></tr>
  {failure_rows}
</table>
"""
    return page(f"{result.get('flow', 'flow')} Report", body)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, help="input result.json")
    parser.add_argument("--html-out", required=True, help="output report.html")
    parser.add_argument("--json-out", help="optional copied report.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result_path = Path(args.result).resolve()
        result = read_json(result_path)
        html_out = Path(args.html_out).resolve()
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(render_report(result), encoding="utf-8")
        if args.json_out:
            write_json(result, Path(args.json_out).resolve())
        print(f"Wrote report: {html_out}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
