# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Normalized DV/FV result schemas.

The dashboard consumes plain JSON records so it can be generated without EDA
tools or a database server. Keep this schema tool-neutral: a DV simulation, a
Verilator compile smoke, and an FV connectivity run should all fit in the same
envelope.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_SKIP = "SKIP"
NON_PASS_STATUSES = {STATUS_FAIL, "ERROR", "TIMEOUT", STATUS_UNKNOWN}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_git(repo_root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return proc.stdout.strip()


def git_metadata(repo_root: Path) -> dict[str, str]:
    return {
        "sha": _run_git(repo_root, ["rev-parse", "HEAD"]),
        "short_sha": _run_git(repo_root, ["rev-parse", "--short", "HEAD"]),
        "branch": _run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"]),
    }


def pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 2)


def _status_count(statuses: list[str]) -> dict[str, int]:
    return {
        "passing": sum(1 for status in statuses if status == STATUS_PASS),
        "failing": sum(1 for status in statuses if status in {"FAIL", "ERROR", "TIMEOUT"}),
        "skipped": sum(1 for status in statuses if status == STATUS_SKIP),
        "unknown": sum(1 for status in statuses if status == STATUS_UNKNOWN),
    }


def _merge_failure_buckets(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        flow = str(result.get("flow", ""))
        buckets = list(result.get("failure_buckets") or [])
        for test in result.get("tests_detail") or []:
            for bucket in test.get("failure_buckets") or []:
                b = dict(bucket)
                if test.get("log"):
                    examples = list(b.get("examples") or [])
                    if test["log"] not in examples:
                        examples.append(test["log"])
                    b["examples"] = examples
                buckets.append(b)
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            kind = str(bucket.get("kind") or "unknown")
            signature = str(bucket.get("signature") or bucket.get("reason") or "unclassified")
            key = (kind, signature)
            entry = merged.setdefault(
                key,
                {
                    "kind": kind,
                    "signature": signature,
                    "count": 0,
                    "flows": [],
                    "affected": [],
                    "examples": [],
                },
            )
            entry["count"] += int(bucket.get("count") or 1)
            if flow and flow not in entry["flows"]:
                entry["flows"].append(flow)
            for affected in bucket.get("affected") or []:
                if affected not in entry["affected"]:
                    entry["affected"].append(affected)
            for example in bucket.get("examples") or []:
                if example and example not in entry["examples"] and len(entry["examples"]) < 5:
                    entry["examples"].append(example)
    return sorted(
        merged.values(), key=lambda item: (-int(item["count"]), item["kind"], item["signature"])
    )


def run_completed(result: dict[str, Any]) -> bool | None:
    """The record's `tests.completed`: `None` when the producer did not say."""
    tests = result.get("tests")
    completed = tests.get("completed") if isinstance(tests, dict) else None
    return completed if isinstance(completed, bool) else None


def _category_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories: dict[str, dict[str, Any]] = {}
    for result in results:
        if run_completed(result) is False:
            continue
        flow = str(result.get("flow", ""))
        for test in result.get("tests_detail") or []:
            category = str(test.get("category") or flow or "uncategorized")
            entry = categories.setdefault(
                category,
                {
                    "category": category,
                    "total": 0,
                    "passing": 0,
                    "failing": 0,
                    "skipped": 0,
                    "unknown": 0,
                    "flows": [],
                },
            )
            entry["total"] += 1
            status = str(test.get("status") or STATUS_UNKNOWN)
            counts = _status_count([status])
            for key in ("passing", "failing", "skipped", "unknown"):
                entry[key] += counts[key]
            if flow and flow not in entry["flows"]:
                entry["flows"].append(flow)
    for entry in categories.values():
        entry["pass_rate"] = pct(int(entry["passing"]), int(entry["total"]))
    return sorted(categories.values(), key=lambda item: item["category"])


def _dut_status(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in sorted(results, key=lambda item: item.get("flow", "")):
        tests = result.get("tests", {})
        regression = (
            result.get("regression", {}) if isinstance(result.get("regression"), dict) else {}
        )
        categories = sorted(
            {
                str(test.get("category"))
                for test in result.get("tests_detail") or []
                if test.get("category")
            }
        )
        artifacts = result.get("artifacts", {})
        coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
        holes = (
            coverage.get("holes_summary") if isinstance(coverage.get("holes_summary"), dict) else {}
        )
        rows.append(
            {
                "flow": result.get("flow", ""),
                "kind": result.get("kind", ""),
                # One DUT can report several framework views (e.g. dtp cocotb + dtp uvm);
                # the framework disambiguates rows that share a flow name.
                "framework": result.get("framework", ""),
                "tool": result.get("tool", ""),
                "status": result.get("status", STATUS_UNKNOWN),
                "tests_total": int(tests.get("total") or 0),
                "tests_passing": int(tests.get("passing") or 0),
                "tests_failing": int(tests.get("failing") or 0),
                "tests_skipped": int(tests.get("skipped") or 0),
                "tests_unknown": int(tests.get("unknown") or 0),
                "tests_completed": tests.get("completed"),
                "pass_rate": tests.get("pass_rate"),
                "category_count": len(categories),
                "categories": categories,
                "failed_tests": len(regression.get("failed_tests") or []),
                "flaky_tests": len(regression.get("flaky_tests") or []),
                "coverage_total_percent": coverage.get("total_percent"),
                "coverage_status": coverage.get("status"),
                "coverage_threshold": coverage.get("threshold"),
                "coverage_threshold_met": coverage.get("threshold_met"),
                "coverage_details_available": coverage.get("details_available"),
                "coverage_open_holes": holes.get("open"),
                "coverage_accepted_holes": holes.get("accepted"),
                "coverage_unclassified_holes": holes.get("unclassified"),
                "coverage_comparison_key": coverage.get("comparison_key"),
                "report": artifacts.get("report") or artifacts.get("html") or "",
                "run_dir": artifacts.get("run_dir")
                or (result.get("run_metadata") or {}).get("run_dir", ""),
            }
        )
    return rows


def _coverage_closure_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_dut: list[dict[str, Any]] = []
    by_category: dict[str, dict[str, Any]] = {}
    details_available = 0
    threshold_failures = 0
    for result in sorted(results, key=lambda item: item.get("flow", "")):
        coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
        holes = (
            coverage.get("holes_summary") if isinstance(coverage.get("holes_summary"), dict) else {}
        )
        available = bool(coverage.get("details_available"))
        details_available += int(available)
        policy_thresholds = [
            outcome
            for outcome in coverage.get("policy_thresholds", [])
            if isinstance(outcome, dict)
        ]
        failed_thresholds = sum(1 for outcome in policy_thresholds if not outcome.get("met"))
        threshold_failures += failed_thresholds
        by_dut.append(
            {
                "dut": result.get("flow", ""),
                "framework": result.get("framework", ""),
                "tool": result.get("tool", ""),
                "details_available": available,
                "open": holes.get("open"),
                "accepted": holes.get("accepted"),
                "unclassified": holes.get("unclassified"),
                "native_point_count": holes.get("native_point_count"),
                "hole_group_count": holes.get("hole_group_count"),
                "threshold_failures": failed_thresholds,
                "comparison_key": coverage.get("comparison_key"),
            }
        )
        for category, count in (holes.get("by_category") or {}).items():
            entry = by_category.setdefault(
                str(category),
                {
                    "category": str(category),
                    "native_point_count": 0,
                    "duts": [],
                },
            )
            entry["native_point_count"] += int(count or 0)
            flow = str(result.get("flow", ""))
            if flow and flow not in entry["duts"]:
                entry["duts"].append(flow)
    return {
        "details_available": details_available,
        "details_missing": max(len(results) - details_available, 0),
        "threshold_failures": threshold_failures,
        "by_dut": by_dut,
        "by_category": sorted(by_category.values(), key=lambda item: item["category"]),
    }


def make_trend_point(summary: dict[str, Any]) -> dict[str, Any]:
    per_dut = []
    for result in summary.get("results") or []:
        coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
        per_dut.append(
            {
                "flow": result.get("flow"),
                "framework": result.get("framework"),
                "tool": result.get("tool"),
                "target": coverage.get("target"),
                "comparison_key": coverage.get("comparison_key"),
                "status": result.get("status"),
                "coverage_status": coverage.get("status"),
                "threshold_met": coverage.get("threshold_met"),
                "raw_metrics": coverage.get("raw_metrics", {}),
                "effective_metrics": coverage.get("effective_metrics", {}),
                "holes_summary": coverage.get("holes_summary", {}),
            }
        )
    identity_payload = {
        "runs": [
            {
                "flow": result.get("flow"),
                "run_dir": (result.get("artifacts") or {}).get("run_dir"),
                "comparison_key": (result.get("coverage") or {}).get("comparison_key"),
                "git": (result.get("git") or {}).get("sha")
                or (result.get("git") or {}).get("commit"),
            }
            for result in summary.get("results") or []
        ],
    }
    point_id = hashlib.sha256(json.dumps(identity_payload, sort_keys=True).encode()).hexdigest()[
        :16
    ]
    return {
        "id": point_id,
        "generated_at": summary.get("generated_at"),
        "flow_pass_rate": (summary.get("flows") or {}).get("pass_rate"),
        "test_pass_rate": (summary.get("tests") or {}).get("pass_rate"),
        "failed_tests": (summary.get("regression") or {}).get("failed_tests"),
        "flaky_tests": (summary.get("regression") or {}).get("flaky_tests"),
        "per_dut": per_dut,
    }


def update_history(prior: dict[str, Any] | None, summary: dict[str, Any]) -> dict[str, Any]:
    history = dict(prior or {})
    points = list(history.get("points") or [])
    point = make_trend_point(summary)
    points = [existing for existing in points if existing.get("id") != point["id"]]
    points.append(point)
    history.update(
        {
            "schema_version": "0.2",
            "generated_at": utc_now(),
            "points": points,
        }
    )
    return history


def make_result(
    *,
    repo_root: Path,
    flow: str,
    kind: str,
    status: str,
    tool: str = "",
    framework: str = "",
    start_time: str = "",
    end_time: str = "",
    duration_sec: float | None = None,
    tests_total: int = 0,
    tests_passing: int = 0,
    tests_completed: bool | None = None,
    coverage_percent: float | None = None,
    coverage_breakdown: dict[str, float] | None = None,
    coverage_details: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    failure_buckets: list[dict[str, Any]] | None = None,
    source: dict[str, Any] | None = None,
    run_metadata: dict[str, Any] | None = None,
    tests_detail: list[dict[str, Any]] | None = None,
    junit_xml: list[dict[str, Any]] | None = None,
    regression: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build one normalized result record."""
    tests_failing = max(tests_total - tests_passing, 0)
    coverage = dict(coverage_details or {})
    coverage["total_percent"] = coverage_percent
    if coverage_breakdown:
        coverage["metrics"] = dict(coverage_breakdown)
        for name, value in coverage_breakdown.items():
            coverage[f"{name}_percent"] = value
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "flow": flow,
        "kind": kind,
        "tool": tool,
        "framework": framework,
        "status": status,
        "git": git_metadata(repo_root),
        "timing": {
            "start_time": start_time,
            "end_time": end_time,
            "duration_sec": duration_sec,
        },
        "tests": {
            "total": tests_total,
            "passing": tests_passing,
            "failing": tests_failing,
            "completed": tests_completed,
            # A run that stopped before its planned leaves has no denominator.
            "pass_rate": None if tests_completed is False else pct(tests_passing, tests_total),
        },
        "coverage": coverage,
        "artifacts": artifacts or {},
        "failure_buckets": failure_buckets or [],
        "source": source or {},
    }
    if run_metadata:
        payload["run_metadata"] = run_metadata
    if tests_detail is not None:
        payload["tests_detail"] = tests_detail
    if junit_xml is not None:
        payload["junit_xml"] = junit_xml
    if regression is not None:
        payload["regression"] = regression
    if warnings:
        payload["warnings"] = warnings
    return payload


def make_result_from_run_result(run_result: Any, repo_root: Path) -> dict[str, Any]:
    """Convert a launcher ``RunResult`` into one normalized dashboard result record."""
    flow = run_result.command.flow
    status = STATUS_PASS if run_result.passed else STATUS_FAIL
    artifacts = {}
    if run_result.log_path is not None:
        try:
            artifacts["log"] = str(run_result.log_path.resolve().relative_to(repo_root))
        except ValueError:
            artifacts["log"] = str(run_result.log_path.resolve())

    failure_buckets = []
    if not run_result.passed and run_result.log_path is not None and run_result.log_path.exists():
        text = run_result.log_path.read_text(errors="replace")
        signature = next(
            (line.strip() for line in text.splitlines() if line.strip()), "backend command failed"
        )
        failure_buckets = [{"signature": signature, "count": 1}]

    return make_result(
        repo_root=repo_root,
        flow=flow.name,
        kind=flow.kind,
        status=status,
        tool=getattr(flow, "default_tool", ""),
        framework=getattr(flow, "framework", ""),
        duration_sec=round(float(run_result.elapsed_sec), 2),
        tests_total=1,
        tests_passing=1 if run_result.passed else 0,
        artifacts=artifacts,
        failure_buckets=failure_buckets,
        source={
            "collector": "run_dv",
            "step": run_result.command.label,
        },
    )


def make_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a dashboard-level summary from normalized result records."""
    total = len(results)
    passing = sum(1 for result in results if result.get("status") == STATUS_PASS)
    failing = sum(1 for result in results if result.get("status") == STATUS_FAIL)
    unknown = total - passing - failing

    test_total = 0
    test_passing = 0
    test_failing = 0
    test_skipped = 0
    test_unknown = 0
    coverage_values: list[float] = []
    junit_total = 0
    junit_missing = 0
    warning_count = 0
    failed_tests = 0
    flaky_tests = 0
    incomplete_runs = 0
    for result in results:
        tests = result.get("tests", {})
        if run_completed(result) is False:
            # Its leaves would lend the aggregate a rate no run earned; the record still
            # counts as a failing flow and keeps its failure buckets.
            incomplete_runs += 1
            tests = {}
        test_total += int(tests.get("total") or 0)
        test_passing += int(tests.get("passing") or 0)
        test_failing += int(tests.get("failing") or 0)
        test_skipped += int(tests.get("skipped") or 0)
        test_unknown += int(tests.get("unknown") or 0)
        if tests and result.get("tests_detail"):
            detail_statuses = [
                str(test.get("status") or STATUS_UNKNOWN)
                for test in result.get("tests_detail") or []
            ]
            counts = _status_count(detail_statuses)
            # Prefer detailed skip/unknown counts when available; a record may carry only
            # total/passing/failing.
            test_skipped += counts["skipped"] if not tests.get("skipped") else 0
            test_unknown += counts["unknown"] if not tests.get("unknown") else 0
        regression = result.get("regression", {})
        if isinstance(regression, dict):
            failed_tests += len(regression.get("failed_tests") or [])
            flaky_tests += len(regression.get("flaky_tests") or [])
        for entry in result.get("junit_xml") or []:
            junit_total += 1
            if not entry.get("exists", True):
                junit_missing += 1
        warning_count += len(result.get("warnings") or [])
        cov = result.get("coverage", {}).get("total_percent")
        if isinstance(cov, (int, float)):
            coverage_values.append(float(cov))

    closure = _coverage_closure_summary(results)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "flows": {
            "total": total,
            "passing": passing,
            "failing": failing,
            "unknown": unknown,
            "pass_rate": pct(passing, total),
        },
        "tests": {
            "total": test_total,
            "passing": test_passing,
            "failing": test_failing
            if test_failing
            else max(test_total - test_passing - test_skipped - test_unknown, 0),
            "skipped": test_skipped,
            "unknown": test_unknown,
            "pass_rate": pct(test_passing, test_total),
            "incomplete_runs": incomplete_runs,
        },
        "coverage": {
            "average_total_percent": None,
            "cross_tool_average_disabled": True,
            "available": len(coverage_values),
            "missing": max(total - len(coverage_values), 0),
        },
        "coverage_closure": closure,
        "regression": {
            "failed_tests": failed_tests,
            "flaky_tests": flaky_tests,
        },
        "junit_xml": {
            "total": junit_total,
            "missing": junit_missing,
        },
        "warnings": {
            "total": warning_count,
        },
        "dut_status": _dut_status(results),
        "categories": _category_summary(results),
        "failure_buckets": _merge_failure_buckets(results),
        "results": results,
    }


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
