# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate an OpenTitan-style static dashboard from result JSON files."""

from __future__ import annotations

import argparse
import glob as globlib
import sys
from pathlib import Path

from dashboard.html import COVERAGE_FIELDS, coverage_value, fmt, link, page
from dashboard.schema import make_summary, read_json, update_history, write_json


def _default_report_link(result: dict) -> str:
    artifacts = result.get("artifacts", {})
    return artifacts.get("report") or artifacts.get("html") or ""


def _card(label: str, value: object, detail: object = "") -> str:
    detail_html = f'<div class="small">{fmt(detail)}</div>' if detail not in (None, "") else ""
    return f'<div class="card"><div class="label">{fmt(label)}</div><div class="value">{fmt(value)}</div>{detail_html}</div>'


def _status_cards(summary: dict) -> str:
    flows = summary.get("flows", {})
    tests = summary.get("tests", {})
    closure = summary.get("coverage_closure", {})
    regression = summary.get("regression", {})
    junit = summary.get("junit_xml", {})
    warnings = summary.get("warnings", {})
    incomplete_runs = int(tests.get("incomplete_runs") or 0)
    test_rate_detail = f"{tests.get('passing')} / {tests.get('total')} passing"
    if incomplete_runs:
        test_rate_detail += f"; {incomplete_runs} incomplete run(s) excluded"
    cards = [
        _card(
            "Flow Pass Rate",
            flows.get("pass_rate"),
            f"{flows.get('passing')} / {flows.get('total')} passing",
        ),
        _card("Test Pass Rate", tests.get("pass_rate"), test_rate_detail),
        _card(
            "Fail / Skip / Unknown",
            f"{tests.get('failing')} / {tests.get('skipped')} / {tests.get('unknown')}",
        ),
        _card("Failed Tests", regression.get("failed_tests")),
        _card("Flaky Tests", regression.get("flaky_tests")),
        _card(
            "Coverage Details",
            closure.get("details_available"),
            f"{closure.get('details_missing')} unavailable",
        ),
        _card("Coverage Threshold Failures", closure.get("threshold_failures")),
        _card("JUnit XML", junit.get("total"), f"{junit.get('missing')} missing"),
        _card("Collector Warnings", warnings.get("total")),
    ]
    return '<div class="cards">' + "\n".join(cards) + "</div>"


def _dut_rows(summary: dict) -> str:
    rows = []
    for row in summary.get("dut_status") or []:
        report_href = row.get("report") or ""
        flow = str(row.get("flow") or "")
        flow_cell = link(report_href, flow) if report_href else fmt(flow)
        categories = ", ".join(row.get("categories") or [])
        pass_rate = (
            "incomplete run" if row.get("tests_completed") is False else fmt(row.get("pass_rate"))
        )
        rows.append(
            "<tr>"
            f"<td>{flow_cell}</td>"
            f"<td>{fmt(row.get('status'))}</td>"
            f"<td>{fmt(row.get('tool'))}</td>"
            f"<td>{fmt(row.get('tests_passing'))}</td>"
            f"<td>{fmt(row.get('tests_total'))}</td>"
            f"<td>{fmt(row.get('tests_failing'))}</td>"
            f"<td>{fmt(row.get('tests_skipped'))}</td>"
            f"<td>{fmt(row.get('tests_unknown'))}</td>"
            f"<td>{pass_rate}</td>"
            f"<td>{fmt(row.get('failed_tests'))}</td>"
            f"<td>{fmt(row.get('flaky_tests'))}</td>"
            f"<td>{fmt(row.get('coverage_total_percent'))}</td>"
            f'<td class="{fmt(row.get("coverage_status"))}">{fmt(row.get("coverage_status"))}</td>'
            f"<td>{fmt(row.get('coverage_threshold'))}</td>"
            f"<td>{fmt(row.get('coverage_threshold_met'))}</td>"
            f"<td>{fmt(row.get('coverage_open_holes'))}</td>"
            f"<td>{fmt(row.get('coverage_accepted_holes'))}</td>"
            f"<td>{fmt(row.get('coverage_unclassified_holes'))}</td>"
            f"<td>{fmt(row.get('category_count'))}</td>"
            f"<td>{fmt(categories)}</td>"
            f"<td>{fmt(row.get('run_dir'))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="21">No DUT status rows.</td></tr>'


def _category_rows(summary: dict) -> str:
    rows = []
    for row in summary.get("categories") or []:
        rows.append(
            "<tr>"
            f"<td>{fmt(row.get('category'))}</td>"
            f"<td>{fmt(row.get('passing'))}</td>"
            f"<td>{fmt(row.get('total'))}</td>"
            f"<td>{fmt(row.get('failing'))}</td>"
            f"<td>{fmt(row.get('skipped'))}</td>"
            f"<td>{fmt(row.get('unknown'))}</td>"
            f"<td>{fmt(row.get('pass_rate'))}</td>"
            f"<td>{fmt(', '.join(row.get('flows') or []))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="8">No category data collected.</td></tr>'


def _coverage_category_rows(summary: dict) -> str:
    rows = []
    closure = summary.get("coverage_closure", {})
    for row in closure.get("by_category") or []:
        rows.append(
            "<tr>"
            f"<td>{fmt(row.get('category'))}</td>"
            f"<td>{fmt(row.get('native_point_count'))}</td>"
            f"<td>{fmt(', '.join(row.get('duts') or []))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or ('<tr><td colspan="3">No coverage category data collected.</td></tr>')


def _coverage_threshold_rows(summary: dict) -> str:
    rows = []
    for result in summary.get("results") or []:
        coverage = result.get("coverage", {})
        for outcome in coverage.get("policy_thresholds") or []:
            rows.append(
                "<tr>"
                f"<td>{fmt(result.get('flow'))}</td>"
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
        '<tr><td colspan="8">No coverage policy thresholds recorded.</td></tr>'
    )


def _failure_bucket_rows(summary: dict) -> str:
    rows = []
    for bucket in summary.get("failure_buckets") or []:
        example = next(iter(bucket.get("examples") or []), "")
        rows.append(
            "<tr>"
            f"<td>{fmt(bucket.get('kind'))}</td>"
            f"<td>{fmt(bucket.get('signature'))}</td>"
            f"<td>{fmt(bucket.get('count'))}</td>"
            f"<td>{fmt(', '.join(bucket.get('flows') or []))}</td>"
            f"<td>{link(example, example) if example else '--'}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="5">No failure buckets recorded.</td></tr>'


def _trend_rows(history: dict | None) -> str:
    if not history:
        return '<tr><td colspan="10">No comparable coverage trend history available.</td></tr>'
    rows = []
    for point in (history.get("points") or [])[-20:]:
        for dut in point.get("per_dut") or []:
            raw = dut.get("raw_metrics") or {}
            effective = dut.get("effective_metrics") or {}
            metric_names = sorted(set(raw) | set(effective))
            if not metric_names:
                metric_names = [""]
            for metric in metric_names:
                holes = dut.get("holes_summary") or {}
                rows.append(
                    "<tr>"
                    f"<td>{fmt(point.get('generated_at'))}</td>"
                    f"<td>{fmt(dut.get('flow'))}</td>"
                    f"<td>{fmt(dut.get('tool'))}</td>"
                    f"<td>{fmt(dut.get('target'))}</td>"
                    f"<td>{fmt(metric)}</td>"
                    f"<td>{fmt(raw.get(metric))}</td>"
                    f"<td>{fmt(effective.get(metric))}</td>"
                    f"<td>{fmt(holes.get('open'))}</td>"
                    f"<td>{fmt(dut.get('threshold_met'))}</td>"
                    f"<td>{fmt(dut.get('comparison_key'))}</td>"
                    "</tr>"
                )
    return "\n".join(rows) or (
        '<tr><td colspan="10">No comparable coverage trend history available.</td></tr>'
    )


def render_dashboard(summary: dict, history: dict | None = None) -> str:
    rows = []
    coverage_headers = "".join(f"<th>{fmt(label)}</th>" for _, label in COVERAGE_FIELDS)
    for result in sorted(summary.get("results", []), key=lambda item: item.get("flow", "")):
        tests = result.get("tests", {})
        git = result.get("git", {})
        status = result.get("status", "UNKNOWN")
        flow = result.get("flow", "")
        report_href = _default_report_link(result)
        flow_cell = link(report_href, flow) if report_href else fmt(flow)
        coverage_cells = "".join(
            f"<td>{fmt(coverage_value(result, name))}</td>" for name, _ in COVERAGE_FIELDS
        )
        regression = (
            result.get("regression", {}) if isinstance(result.get("regression"), dict) else {}
        )
        pass_rate = (
            "incomplete run" if tests.get("completed") is False else fmt(tests.get("pass_rate"))
        )
        rows.append(
            "<tr>"
            f"<td>{flow_cell}</td>"
            f"<td>{fmt(result.get('kind'))}</td>"
            f"<td>{fmt(result.get('tool'))}</td>"
            f'<td class="{fmt(status)}">{fmt(status)}</td>'
            f"<td>{fmt(tests.get('passing'))}</td>"
            f"<td>{fmt(tests.get('total'))}</td>"
            f"<td>{pass_rate}</td>"
            f"<td>{fmt(len(regression.get('failed_tests') or []))}</td>"
            f"<td>{fmt(len(regression.get('flaky_tests') or []))}</td>"
            f"{coverage_cells}"
            f"<td>{fmt(git.get('short_sha'))}</td>"
            f"<td>{fmt(git.get('branch'))}</td>"
            "</tr>"
        )
    table_rows = "\n".join(rows) or '<tr><td colspan="17">No results found.</td></tr>'
    flows = summary.get("flows", {})
    tests = summary.get("tests", {})
    regression = summary.get("regression", {})
    body = f"""
<h1>OCAH DV/FV Dashboard</h1>
<p class="meta">Generated at {fmt(summary.get("generated_at"))}</p>

<h2>Summary</h2>
{_status_cards(summary)}
<table>
  <tr><th>Passing Flows</th><th>Total Flows</th><th>Flow Pass Rate</th><th>Passing Tests</th><th>Total Tests</th><th>Test Pass Rate</th><th>Failed Tests</th><th>Flaky Tests</th></tr>
  <tr>
    <td>{fmt(flows.get("passing"))}</td>
    <td>{fmt(flows.get("total"))}</td>
    <td>{fmt(flows.get("pass_rate"))}</td>
    <td>{fmt(tests.get("passing"))}</td>
    <td>{fmt(tests.get("total"))}</td>
    <td>{fmt(tests.get("pass_rate"))}</td>
    <td>{fmt(regression.get("failed_tests"))}</td>
    <td>{fmt(regression.get("flaky_tests"))}</td>
  </tr>
</table>

<h2>Per-DUT Status</h2>
<table>
  <tr><th>DUT</th><th>Status</th><th>Tool</th><th>Passing</th><th>Total</th><th>Failing</th><th>Skipped</th><th>Unknown</th><th>Pass Rate</th><th>Failed Tests</th><th>Flaky Tests</th><th>Coverage</th><th>Coverage Status</th><th>Threshold</th><th>Threshold Met</th><th>Open Holes</th><th>Accepted Holes</th><th>Unclassified</th><th>Categories</th><th>Category List</th><th>Run Dir</th></tr>
  {_dut_rows(summary)}
</table>

<h2>Per-Category Status</h2>
<table>
  <tr><th>Category</th><th>Passing</th><th>Total</th><th>Failing</th><th>Skipped</th><th>Unknown</th><th>Pass Rate</th><th>DUTs</th></tr>
  {_category_rows(summary)}
</table>

<h2>Coverage Closure by Category</h2>
<table>
  <tr><th>Coverage Category</th><th>Native Hole Points</th><th>DUTs</th></tr>
  {_coverage_category_rows(summary)}
</table>

<h2>Coverage Policy Thresholds</h2>
<table>
  <tr><th>DUT</th><th>Rule</th><th>Metric</th><th>Population</th><th>Actual</th><th>Minimum</th><th>Unclassified</th><th>Met</th></tr>
  {_coverage_threshold_rows(summary)}
</table>

<h2>Failure Buckets</h2>
<table>
  <tr><th>Kind</th><th>Signature</th><th>Count</th><th>DUTs</th><th>Example</th></tr>
  {_failure_bucket_rows(summary)}
</table>

<h2>Trend</h2>
<table>
  <tr><th>Generated At</th><th>DUT</th><th>Tool</th><th>Target</th><th>Metric</th><th>Raw</th><th>Effective</th><th>Open Holes</th><th>Threshold Met</th><th>Comparison Key</th></tr>
  {_trend_rows(history)}
</table>

<h2>Flow Results</h2>
<table>
  <tr>
    <th>Name</th>
    <th>Kind</th>
    <th>Tool</th>
    <th>Status</th>
    <th>Passing</th>
    <th>Total</th>
    <th>Pass Rate</th>
    <th>Failed Tests</th>
    <th>Flaky Tests</th>
    {coverage_headers}
    <th>Revision</th>
    <th>Branch</th>
  </tr>
  {table_rows}
</table>
"""
    return page("OCAH DV/FV Dashboard", body)


def _load_results(paths: list[str]) -> list[dict]:
    results = []
    for pattern in paths:
        matches = (
            [Path(path) for path in sorted(globlib.glob(pattern))]
            if any(ch in pattern for ch in "*?[]")
            else [Path(pattern)]
        )
        for path in matches:
            if path.exists():
                results.append(read_json(path))
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results", nargs="+", required=True, help="result JSON paths or glob patterns"
    )
    parser.add_argument(
        "--html-out", help="optional output index.html; omit for a data-only aggregate"
    )
    parser.add_argument("--summary-out", required=True, help="output summary.json")
    parser.add_argument("--history-in", help="optional existing trend history JSON")
    parser.add_argument("--history-out", help="optional output trend history JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        results = _load_results(args.results)
        summary = make_summary(results)
        history = None
        if args.history_in and Path(args.history_in).is_file():
            history = read_json(Path(args.history_in).resolve())
        if args.history_out:
            history = update_history(history, summary)
        if args.html_out:
            html_out = Path(args.html_out).resolve()
            html_out.parent.mkdir(parents=True, exist_ok=True)
            html_out.write_text(render_dashboard(summary, history), encoding="utf-8")
        write_json(summary, Path(args.summary_out).resolve())
        if args.history_out:
            write_json(history or {}, Path(args.history_out).resolve())
        if args.html_out:
            print(f"Wrote dashboard: {html_out}")
        print(f"Wrote summary  : {Path(args.summary_out).resolve()}")
        if args.history_out:
            print(f"Wrote history  : {Path(args.history_out).resolve()}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
