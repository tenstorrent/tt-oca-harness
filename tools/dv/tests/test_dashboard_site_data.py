# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""End-to-end contract for the data the documentation site renders.

Three runs are written with the runner's own result writers, collected and aggregated by
the dashboard package, and trimmed by tools/doc/trim_dashboard_data.py, the reader the site
pages are built against. The trimmed documents must match the expected content exactly, and
every field the trim script names must be present in the producer's output: the script omits
a missing field silently, and the page then renders that cell as unavailable.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "doc"))

import aggregate_test_history  # noqa: E402
import render_badges  # noqa: E402
import trim_dashboard_data as trim  # noqa: E402
from dashboard.collect_results import collect_flow_result, stage_coverage_artifacts  # noqa: E402
from dashboard.schema import SCHEMA_VERSION, make_summary, update_history  # noqa: E402
from runlib.models import StageResult  # noqa: E402
from runlib.results import (  # noqa: E402
    fragment_payload,
    regression_payload,
    result_payload,
    write_result,
)
from test_results_completion import (  # noqa: E402
    INTERRUPTION,
    TOOL,
    interrupted_progress,
    make_flow,
)

STARTED_AT = "2026-09-01T00:00:00+00:00"
ENDED_AT = "2026-09-01T00:00:01+00:00"
GIT = {"commit": "0" * 40, "branch": "main", "dirty": "false"}
GENERATED_AT = "<generated_at>"
PLANNED_LEAVES = 3


class Leaf(NamedTuple):
    item: str
    seed: int
    attempt: int
    status: str
    reason: str


PASSING = (
    Leaf("t_alpha", 11, 0, "PASS", ""),
    Leaf("t_beta", 12, 0, "PASS", ""),
    Leaf("t_gamma", 13, 0, "PASS", ""),
)
RETRIED = (
    Leaf("t_alpha", 11, 0, "PASS", ""),
    Leaf("t_beta", 12, 0, "FAIL", "scoreboard mismatch"),
    Leaf("t_beta", 12, 1, "PASS", ""),
    Leaf("t_gamma", 13, 0, "FAIL", "timeout waiting for done"),
)
STARTED = (Leaf("t_alpha", 11, 0, "PASS", ""),)

COVERAGE_SUMMARY = {
    "schema_version": 2,
    "status": "PASS",
    "overall_percent": 47.5,
    "metrics": {"line": 55.0, "branch": 40.0},
    "threshold": 0.0,
    "threshold_met": True,
    "backend": TOOL,
    "comparison_key": "fixture:verilator:default",
    "scope_fingerprint": "scope",
    "policy_fingerprint": None,
    "details_available": True,
    "policy_thresholds": [],
    "holes_summary": {
        "details_available": True,
        "observations_complete": True,
        "native_point_count": 2,
        "hole_group_count": 0,
        "open": 2,
        "accepted": 0,
        "unclassified": 2,
        "by_metric": {},
        "by_category": {},
        "by_disposition": {},
        "by_status": {},
        "samples": [],
        "sample_truncated": False,
    },
}
COVERAGE_DETAILS = {
    "schema_version": 1,
    "details_available": True,
    "metrics": [
        {"metric_family": "line", "raw_percent": 55.0, "effective_percent": 60.0},
        {"metric_family": "branch", "raw_percent": 40.0, "effective_percent": 40.0},
    ],
}
COVERAGE_MANIFEST = {
    "schema_version": 2,
    "backend": TOOL,
    "parser": TOOL,
    "tool_version": "5.0",
    "supported_metrics": ["line", "branch"],
    "target": "default",
    "build_fingerprint": "fp",
    "inputs": [],
    "artifacts": {},
}
EFFECTIVE_METRICS = {"line": 60.0, "branch": 40.0}


def leaf_result(leaf: Leaf) -> StageResult:
    """The stage result of one attempt, as the sim stage grades it."""
    passed = leaf.status == "PASS"
    buckets = (
        []
        if passed
        else [{"kind": "scoreboard", "signature": leaf.reason, "count": 1, "examples": []}]
    )
    return StageResult(
        stage="sim",
        item=leaf.item,
        status=leaf.status,
        return_code=0 if passed else 1,
        duration_sec=1.5 + leaf.attempt,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        log=f"dut/build/runs/r/{leaf.item}/seed_{leaf.seed}/attempt_{leaf.attempt}/logs/sim.log",
        failure_buckets=buckets,
        reason=leaf.reason,
        metadata={"seed": leaf.seed, "attempt": leaf.attempt, "debug_only": False},
        target="default",
    )


def job_record(leaf: Leaf, result: StageResult, result_json: str) -> dict[str, Any]:
    """One regression.json job entry for an attempt."""
    return {
        "stage": "sim",
        "item": leaf.item,
        "target": "default",
        "seed": leaf.seed,
        "attempt": leaf.attempt,
        "status": result.status,
        "return_code": result.return_code,
        "reason": result.reason,
        "duration_sec": result.duration_sec,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "log": result.log,
        "artifacts": {},
        "failure_buckets": result.failure_buckets,
        "parser": None,
        "metadata": result.metadata,
        "result_json": result_json,
    }


def stage_result(name: str) -> StageResult:
    """A passing run-level stage such as cov_merge or cov_report."""
    return StageResult(
        stage=name,
        item=None,
        status="PASS",
        return_code=0,
        duration_sec=0.5,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        log=f"dut/build/runs/r/stages/{name}/logs/{name}.log",
        reason="process completed successfully",
        metadata={"target": "default"},
    )


def normalised(document: Any) -> Any:
    """The document with every timestamp replaced by one sentinel."""
    if isinstance(document, dict):
        return {
            key: GENERATED_AT if key == "generated_at" else normalised(value)
            for key, value in document.items()
        }
    if isinstance(document, list):
        return [normalised(value) for value in document]
    return document


def test_row(leaf: Leaf) -> dict[str, Any]:
    """The tests.json row the site shows for one attempt."""
    return {
        "name": leaf.item,
        "status": leaf.status,
        "category": "fixture",
        "seed": leaf.seed,
        "duration_sec": 1.5 + leaf.attempt,
        "stage": "sim",
    }


def expected_site_data(
    leaves: tuple[Leaf, ...],
    *,
    tests_total: int,
    pass_rate: float | None,
    flow_pass_rate: float,
    failed_tests: int = 0,
    flaky_tests: int = 0,
    coverage_status: str = "SKIP",
    effective_metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    """The three trimmed documents for one run of the fixture DUT."""
    effective_metrics = {} if effective_metrics is None else effective_metrics
    return {
        "summary": {
            "generated_at": GENERATED_AT,
            "dut_status": [{"flow": "fixture", "tests_total": tests_total, "pass_rate": pass_rate}],
            "results": [{"flow": "fixture", "coverage": {"effective_metrics": effective_metrics}}],
        },
        "tests": {
            "generated_at": GENERATED_AT,
            "flows": {"fixture": [test_row(leaf) for leaf in leaves]},
        },
        "history": {
            "points": [
                {
                    "generated_at": GENERATED_AT,
                    "test_pass_rate": pass_rate,
                    "flow_pass_rate": flow_pass_rate,
                    "failed_tests": failed_tests,
                    "flaky_tests": flaky_tests,
                    "per_dut": [
                        {
                            "flow": "fixture",
                            "coverage_status": coverage_status,
                            "effective_metrics": effective_metrics,
                        }
                    ],
                }
            ]
        },
    }


class SiteDataCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "dut" / "build" / "runs" / "r"
        self.run_dir.mkdir(parents=True)
        self.flow = make_flow(self.root)

    def write_run(
        self, leaves: tuple[Leaf, ...], *, coverage: bool = False, interrupted: bool = False
    ) -> None:
        """Write the run tree the runner leaves: leaf files, result.json, regression.json."""
        args = Namespace(dry_run=False, verbose=False, quiet=True, cov=coverage)
        jobs: list[dict[str, Any]] = []
        finals: dict[tuple[str, int], StageResult] = {}
        for leaf in leaves:
            result = leaf_result(leaf)
            path = self.run_dir / leaf.item / f"seed_{leaf.seed}" / f"attempt_{leaf.attempt}"
            write_result(
                path / "result.json",
                fragment_payload(
                    flow=self.flow,
                    root=self.root,
                    tool=TOOL,
                    run_dir=self.run_dir,
                    item=leaf.item,
                    seed=leaf.seed,
                    result=result,
                ),
            )
            jobs.append(
                job_record(leaf, result, str((path / "result.json").relative_to(self.root)))
            )
            finals[(leaf.item, leaf.seed)] = result
        # The run-level result lists one entry per leaf, the regression file one per attempt.
        stages = list(finals.values())
        if coverage:
            self.write_coverage_report()
            stages += [stage_result("cov_merge"), stage_result("cov_report")]
        ending: dict[str, Any] = {}
        if interrupted:
            ending = {
                "status_override": "ERROR",
                "progress": interrupted_progress(PLANNED_LEAVES, len(finals)),
                "interruption": INTERRUPTION,
            }
        common: dict[str, Any] = {
            "flow": self.flow,
            "root": self.root,
            "tool": TOOL,
            "run_dir": self.run_dir,
            "stages": stages,
            "args": args,
            "items": sorted({leaf.item for leaf in leaves}),
            "versions": {TOOL: "5.0"},
            "git_metadata": GIT,
            "planned_leaves": PLANNED_LEAVES,
        }
        write_result(
            self.run_dir / "result.json", result_payload(dry_run=False, **common, **ending)
        )
        write_result(
            self.run_dir / "stages" / "regress" / "regression.json",
            regression_payload(jobs=jobs, elapsed_sec=9.0, **common, **ending),
        )

    def write_coverage_report(self) -> None:
        report = self.run_dir / "cov" / "report"
        report.mkdir(parents=True)
        (report / "summary.json").write_text(json.dumps(COVERAGE_SUMMARY), encoding="utf-8")
        (report / "coverage-details.json").write_text(
            json.dumps(COVERAGE_DETAILS), encoding="utf-8"
        )
        (report / "policy-application.json").write_text("{}\n", encoding="utf-8")
        (self.run_dir / "cov" / "coverage.json").write_text(
            json.dumps(COVERAGE_MANIFEST), encoding="utf-8"
        )

    def publish(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Collect, aggregate and trim the run; return record, summary, history and trimmed."""
        bundle = self.root / "bundle"
        bundle.mkdir()
        record = collect_flow_result(self.root, self.flow, self.run_dir)
        stage_coverage_artifacts(self.root, record, bundle / "fixture.result.json")
        self.assertEqual(record["schema_version"], SCHEMA_VERSION)
        self.assertIn(record["status"], {"PASS", "FAIL", "UNKNOWN"})
        summary = make_summary([record])
        history = update_history(None, summary)
        (bundle / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (bundle / "history.json").write_text(json.dumps(history), encoding="utf-8")
        site = self.root / "site"
        rc = trim.trim_summary(
            Namespace(
                source=bundle / "summary.json",
                output=site / "summary.json",
                tests_out=site / "tests.json",
            )
        )
        self.assertEqual(rc, 0)
        rc = trim.trim_history(
            Namespace(source=bundle / "history.json", output=site / "history.json")
        )
        self.assertEqual(rc, 0)
        trimmed = {
            name: json.loads((site / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("summary", "tests", "history")
        }
        return record, summary, history, trimmed

    def assert_trim_terms_present(self, summary: dict[str, Any], history: dict[str, Any]) -> None:
        """Every field the trim script names exists in the producer's output."""
        self.assertLessEqual(set(trim.SUMMARY_KEYS), set(summary))
        for row in summary["dut_status"]:
            self.assertLessEqual(set(trim.DUT_KEYS), set(row), row)
        for result in summary["results"]:
            self.assertLessEqual(set(trim.RESULT_KEYS), set(result))
            self.assertLessEqual(set(trim.COVERAGE_KEYS), set(result["coverage"]))
            for test in result["tests_detail"]:
                self.assertLessEqual(set(trim.TEST_KEYS), set(test), test)
        for point in history["points"]:
            self.assertLessEqual(set(trim.HISTORY_POINT_KEYS), set(point))
            for dut in point["per_dut"]:
                self.assertLessEqual(set(trim.HISTORY_DUT_KEYS), set(dut), dut)


class TrimmedSiteData(SiteDataCase):
    def test_complete_run_with_coverage(self):
        self.write_run(PASSING, coverage=True)
        _, summary, history, trimmed = self.publish()
        self.assertEqual(
            normalised(trimmed),
            expected_site_data(
                PASSING,
                tests_total=3,
                pass_rate=100.0,
                flow_pass_rate=100.0,
                coverage_status="PASS",
                effective_metrics=EFFECTIVE_METRICS,
            ),
        )
        self.assert_trim_terms_present(summary, history)

    def test_complete_run_with_a_retry_and_failures(self):
        self.write_run(RETRIED)
        _, summary, history, trimmed = self.publish()
        self.assertEqual(
            normalised(trimmed),
            expected_site_data(
                RETRIED,
                tests_total=3,
                pass_rate=66.67,
                flow_pass_rate=0.0,
                failed_tests=1,
                flaky_tests=1,
            ),
        )
        self.assert_trim_terms_present(summary, history)

    def test_interrupted_run(self):
        self.write_run(STARTED, interrupted=True)
        _, summary, history, trimmed = self.publish()
        self.assertEqual(
            normalised(trimmed),
            expected_site_data(
                STARTED,
                tests_total=1,
                pass_rate=None,
                flow_pass_rate=0.0,
            ),
        )
        self.assert_trim_terms_present(summary, history)


class SiblingStagingReaders(SiteDataCase):
    """The badge renderer and the test-history aggregator run in the same staging step."""

    def test_badges_read_the_status_rate_and_coverage_total(self):
        self.write_run(PASSING, coverage=True)
        record, summary, _, _ = self.publish()
        badges = render_badges.badges_for(summary["dut_status"][0], record["coverage"])
        self.assertEqual(badges["status"][:2], ("fixture", "passing"))
        self.assertEqual(badges["tests"][:2], ("tests", "100.0 %"))
        self.assertEqual(badges["coverage"][:2], ("coverage", "47.5 %"))

    def test_test_history_reads_every_attempt_with_its_reason(self):
        self.write_run(RETRIED)
        record, _, _, _ = self.publish()
        self.assertEqual(
            aggregate_test_history.tally(record),
            {
                "t_alpha": [{"seed": 11}],
                "t_beta": [{"seed": 12, "reason": "scoreboard mismatch"}, {"seed": 12}],
                "t_gamma": [{"seed": 13, "reason": "timeout waiting for done"}],
            },
        )


if __name__ == "__main__":
    unittest.main()
