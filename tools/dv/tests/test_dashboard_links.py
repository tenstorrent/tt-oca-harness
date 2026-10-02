# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the paths a normalized dashboard record publishes.

A run tree downloaded from CI sits somewhere other than the run directory the runner
recorded. Every path the collector publishes must resolve against the downloaded tree,
and the coverage files it stages beside the record must be the small ones.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.collect_results import (  # noqa: E402
    collect_flow_result,
    stage_coverage_artifacts,
)
from test_dashboard_schema import (  # noqa: E402
    FAILED_TEST_FIELDS,
    FLAKY_TEST_FIELDS,
    HOLES_SUMMARY_FIELDS,
    RECORD_COVERAGE_FIELDS,
    REGRESSION_FIELDS,
    RUN_METADATA_FIELDS,
)
from test_results_completion import make_flow  # noqa: E402

RECORDED_RUN_DIR = "build/ci/runs/fixture/verilator/weekly/42"
COMPILE_LOG = "stages/hdl_compile/logs/hdl_compile.log"
REPORT_FILES = (
    "summary.json",
    "policy-application.json",
    "coverage-details.json",
    "coverage-details.raw.json",
    "coverage.info",
    "fixture_top.sv",
)


def recorded(relative: str) -> str:
    return f"{RECORDED_RUN_DIR}/{relative}"


class RelocatedRunTree(unittest.TestCase):
    """The run tree is extracted under `downloads/`, not under the recorded run directory."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_root = self.root / "downloads" / "dv-run-fixture-verilator-weekly"
        self.flow = make_flow(self.root)
        self.write_run_tree()

    def write_run_tree(self):
        report = self.run_root / "cov" / "report"
        report.mkdir(parents=True)
        for name in REPORT_FILES:
            (report / name).write_text("{}\n" if name.endswith(".json") else "x\n")
        (self.run_root / "cov" / "coverage.json").write_text("{}\n")
        (self.run_root / "cov" / "merged.dat").write_text("x\n")
        (self.run_root / COMPILE_LOG).parent.mkdir(parents=True)
        (self.run_root / COMPILE_LOG).write_text("%Error: x\n")
        native = {
            "schema_version": 1,
            "flow": "fixture",
            "kind": "sim",
            "framework": "cocotb",
            "tool": "verilator",
            "label": "all",
            "status": "PASS",
            "run_dir": RECORDED_RUN_DIR,
            "stages": [
                {
                    "name": "hdl_compile",
                    "status": "PASS",
                    "log": recorded(COMPILE_LOG),
                    "started_at": "2026-09-01T00:00:00+00:00",
                    "ended_at": "2026-09-01T00:00:01+00:00",
                    "duration_sec": 1.0,
                    "failure_buckets": [
                        {
                            "kind": "compile_error",
                            "signature": "%Error",
                            "count": 1,
                            "examples": [recorded(COMPILE_LOG)],
                        }
                    ],
                }
            ],
            "tests": {"total": 1, "passing": 1, "completed": True},
            "coverage": {
                "enabled": True,
                "status": "PASS",
                "total_percent": 50.0,
                "metrics": {"line_percent": 50.0},
                "report": recorded("cov/report"),
                "manifest": recorded("cov/coverage.json"),
                "summary": recorded("cov/report/summary.json"),
                "coverage_details": recorded("cov/report/coverage-details.json"),
                "coverage_details_raw": recorded("cov/report/coverage-details.raw.json"),
                "policy_application": recorded("cov/report/policy-application.json"),
                "merged": recorded("cov/merged.dat"),
                "inputs": [recorded("t_alpha/seed_1/attempt_0/coverage/coverage.dat")],
            },
        }
        (self.run_root / "result.json").write_text(json.dumps(native))
        regression = {
            "schema_version": 1,
            "flow": "fixture",
            "run_dir": RECORDED_RUN_DIR,
            "artifacts": {
                "result_json": recorded("result.json"),
                "regression_json": recorded("stages/regress/regression.json"),
                "coverage_report": recorded("cov/report"),
                "coverage_coverage_details": recorded("cov/report/coverage-details.json"),
                "coverage_coverage_details_raw": recorded("cov/report/coverage-details.raw.json"),
                "coverage_merged": recorded("cov/merged.dat"),
            },
            "jobs": [],
            "failed_tests": [
                {
                    "item": "t_beta",
                    "target": "default",
                    "seed": 7,
                    "status": "FAIL",
                    "reason": "scoreboard mismatch",
                    "duration_sec": 2.0,
                    "attempt_count": 1,
                    "attempts": [{"attempt": 0, "status": "FAIL"}],
                    "log": recorded("t_beta/seed_7/attempt_0/logs/sim.log"),
                    "artifacts": {},
                    "failure_buckets": [],
                    "parser": None,
                    "result_json": recorded("t_beta/seed_7/attempt_0/result.json"),
                    "rerun": "python3 tools/dv/run_dv.py --dut fixture --items t_beta --seed 7",
                }
            ],
            "flaky_tests": [
                {
                    "item": "t_gamma",
                    "target": "default",
                    "seed": 9,
                    "final_status": "PASS",
                    "flaky": True,
                    "flaky_reason": "passed_after_retry",
                    "attempt_count": 2,
                    "failing_attempts": 1,
                    "first_fail_attempt": 0,
                    "first_failure_reason": "timeout",
                    "passed_on_attempt": 1,
                    "attempts": [
                        {"attempt": 0, "status": "FAIL"},
                        {"attempt": 1, "status": "PASS"},
                    ],
                    "log": recorded("t_gamma/seed_9/attempt_1/logs/sim.log"),
                    "result_json": recorded("t_gamma/seed_9/attempt_1/result.json"),
                    "rerun": "python3 tools/dv/run_dv.py --dut fixture --items t_gamma --seed 9",
                }
            ],
            "failure_buckets": [],
        }
        (self.run_root / "stages" / "regress").mkdir(parents=True)
        (self.run_root / "stages" / "regress" / "regression.json").write_text(
            json.dumps(regression)
        )

    def relocated(self, relative: str) -> str:
        return str((self.run_root / relative).relative_to(self.root))

    def collect(self) -> dict:
        record = collect_flow_result(self.root, self.flow, self.run_root)
        self.assertEqual(record["source"]["collector"], "run_dv-result")
        return record

    def test_coverage_paths_follow_the_downloaded_tree(self):
        coverage = self.collect()["coverage"]
        for key, relative in (
            ("report", "cov/report"),
            ("manifest", "cov/coverage.json"),
            ("summary", "cov/report/summary.json"),
            ("policy_application", "cov/report/policy-application.json"),
        ):
            with self.subTest(key=key):
                self.assertEqual(coverage[key], self.relocated(relative))
                self.assertTrue((self.root / coverage[key]).exists())
        self.assertEqual(coverage["status"], "PASS")

    def test_record_carries_only_the_site_fields(self):
        record = self.collect()
        self.assertLessEqual(set(record["coverage"]), RECORD_COVERAGE_FIELDS)
        self.assertLessEqual(
            set(record["coverage"].get("holes_summary") or {}), HOLES_SUMMARY_FIELDS
        )
        for key in ("inputs", "metrics", "line_percent", "merged", "coverage_details"):
            self.assertNotIn(key, record["coverage"])
        self.assertEqual(set(record["run_metadata"]), RUN_METADATA_FIELDS)
        self.assertEqual(record["junit_xml"], {"total": 0, "missing": 0})

    def test_artifacts_mirror_the_rebased_coverage_paths(self):
        artifacts = self.collect()["artifacts"]
        self.assertEqual(artifacts["coverage_report"], self.relocated("cov/report"))
        self.assertEqual(artifacts["coverage_manifest"], self.relocated("cov/coverage.json"))
        self.assertNotIn("coverage_merged", artifacts)
        self.assertEqual(artifacts["run_dir"], RECORDED_RUN_DIR)
        self.assertEqual(artifacts["result_json"], self.relocated("result.json"))

    def test_regression_keeps_the_failed_and_flaky_leaves(self):
        regression = self.collect()["regression"]
        self.assertEqual(set(regression), REGRESSION_FIELDS)
        self.assertEqual([set(entry) for entry in regression["failed_tests"]], [FAILED_TEST_FIELDS])
        self.assertEqual([set(entry) for entry in regression["flaky_tests"]], [FLAKY_TEST_FIELDS])
        self.assertEqual(
            regression["failed_tests"][0],
            {
                "item": "t_beta",
                "seed": 7,
                "status": "FAIL",
                "reason": "scoreboard mismatch",
                "rerun": "python3 tools/dv/run_dv.py --dut fixture --items t_beta --seed 7",
            },
        )
        self.assertEqual(
            regression["flaky_tests"][0],
            {
                "item": "t_gamma",
                "seed": 9,
                "final_status": "PASS",
                "attempt_count": 2,
                "rerun": "python3 tools/dv/run_dv.py --dut fixture --items t_gamma --seed 9",
            },
        )

    def test_failure_bucket_examples_follow_the_downloaded_tree(self):
        buckets = self.collect()["failure_buckets"]
        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0]["examples"], [self.relocated(COMPILE_LOG)])
        self.assertTrue((self.root / buckets[0]["examples"][0]).is_file())

    def test_staging_copies_only_the_small_report_files(self):
        record = self.collect()
        output = self.root / "bundle" / "fixture.result.json"
        stage_coverage_artifacts(self.root, record, output)
        coverage = record["coverage"]
        artifacts = record["artifacts"]
        staged_report = "artifacts/fixture/coverage/report"
        self.assertEqual(coverage["report"], staged_report)
        self.assertEqual(coverage["summary"], f"{staged_report}/summary.json")
        self.assertEqual(coverage["policy_application"], f"{staged_report}/policy-application.json")
        self.assertEqual(coverage["manifest"], "artifacts/fixture/coverage/coverage.json")
        for key in ("report", "summary", "policy_application", "manifest"):
            with self.subTest(key=key):
                self.assertTrue((output.parent / coverage[key]).exists())
                self.assertEqual(artifacts[f"coverage_{key}"], coverage[key])
        self.assertEqual(
            sorted(path.name for path in (output.parent / staged_report).iterdir()),
            ["policy-application.json", "summary.json"],
        )
        for key in ("coverage_details", "coverage_details_raw", "merged"):
            with self.subTest(key=key):
                self.assertNotIn(key, coverage)
                self.assertNotIn(f"coverage_{key}", artifacts)
        self.assertEqual(coverage["source_report"], self.relocated("cov/report"))
        self.assertEqual(coverage["source_summary"], self.relocated("cov/report/summary.json"))
        self.assertEqual(coverage["source_manifest"], self.relocated("cov/coverage.json"))
        self.assertNotIn("source_coverage_details", coverage)

    def test_staging_without_a_report_leaves_the_record_alone(self):
        record = self.collect()
        shutil.rmtree(self.run_root / "cov" / "report")
        output = self.root / "bundle" / "fixture.result.json"
        stage_coverage_artifacts(self.root, record, output)
        self.assertEqual(record["coverage"]["report"], self.relocated("cov/report"))
        self.assertEqual(record["coverage"]["manifest"], "artifacts/fixture/coverage/coverage.json")
        self.assertNotIn("source_report", record["coverage"])


class CoordinatorGradedLeaf(unittest.TestCase):
    """A leaf whose job left no result: the coordinator's JUnit sits in the graded attempt."""

    LEAF = "t_alpha/seed_3"
    JOB_LOGS = ("stages/regress/logs/sim-000000-a0.log", "stages/regress/logs/sim-000000-a1.log")
    SIGNATURE = "ended failed: failed reported with exit code 127 but no result.json appeared"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_root = self.root / "build" / "runs" / "r"
        self.flow = make_flow(self.root)
        for log in self.JOB_LOGS:
            (self.run_root / log).parent.mkdir(parents=True, exist_ok=True)
            (self.run_root / log).write_text("exec: python3: not found\n")
        xml_path = self.run_root / self.LEAF / "attempt_1" / "results" / "results.xml"
        xml_path.parent.mkdir(parents=True)
        xml_path.write_text("<testsuites/>\n")
        bucket = {"kind": "environment_error", "signature": self.SIGNATURE, "count": 1}
        graded = {
            "name": "sim",
            "item": "t_alpha",
            "status": "ERROR",
            "log": self.rel(self.JOB_LOGS[1]),
            "failure_buckets": [bucket],
            "metadata": {"seed": 3, "attempt": 1},
            "result_json": self.rel(f"{self.LEAF}/attempt_1/result.json"),
        }
        result = {
            "schema_version": 1,
            "flow": "fixture",
            "status": "ERROR",
            "run_dir": self.rel(""),
            "stages": [graded],
            "tests": {"total": 1, "passing": 0, "completed": True},
        }
        (self.run_root / "result.json").write_text(json.dumps(result))
        jobs = [
            {
                "stage": "sim",
                "item": "t_alpha",
                "seed": 3,
                "attempt": attempt,
                "status": "ERROR",
                "log": self.rel(log),
                "failure_buckets": [bucket],
                "result_json": self.rel(f"{self.LEAF}/attempt_{attempt}/result.json"),
            }
            for attempt, log in enumerate(self.JOB_LOGS)
        ]
        regression = {
            "schema_version": 1,
            "flow": "fixture",
            "run_dir": self.rel(""),
            "jobs": jobs,
            "failed_tests": [],
            "flaky_tests": [],
            "failure_buckets": [
                {**bucket, "affected": ["t_alpha"], "examples": [self.rel(self.JOB_LOGS[1])]}
            ],
        }
        (self.run_root / "stages" / "regress" / "regression.json").write_text(
            json.dumps(regression)
        )

    def rel(self, relative: str) -> str:
        return str((self.run_root / relative).relative_to(self.root))

    def test_the_graded_attempt_junit_is_found_and_no_job_log_path_is_guessed(self):
        record = collect_flow_result(self.root, self.flow, self.run_root)
        self.assertEqual(record["junit_xml"], {"total": 1, "missing": 0})
        self.assertFalse(
            [w for w in record["warnings"] if w.startswith("JUnit XML missing")],
            record["warnings"],
        )

    def test_a_regression_leaf_bucket_counts_once_with_its_example(self):
        record = collect_flow_result(self.root, self.flow, self.run_root)
        (bucket,) = record["failure_buckets"]
        self.assertEqual((bucket["kind"], bucket["count"]), ("environment_error", 1))
        self.assertEqual(bucket["examples"], [self.rel(self.JOB_LOGS[1])])

    def test_a_leaf_file_written_after_the_grade_fills_only_what_the_record_lacks(self):
        regression_path = self.run_root / "stages" / "regress" / "regression.json"
        regression = json.loads(regression_path.read_text())
        reason = f"environment_error: attempt sim-000000-a1 {self.SIGNATURE}"
        regression["jobs"][1]["reason"] = reason
        regression_path.write_text(json.dumps(regression))
        late = {
            "item": "t_alpha",
            "seed": 3,
            "attempt": 1,
            "status": "PASS",
            "reason": "",
            "duration_sec": 12.5,
            "artifacts": {"results_xml": self.rel(f"{self.LEAF}/attempt_1/results/results.xml")},
        }
        (self.run_root / self.LEAF / "attempt_1" / "result.json").write_text(json.dumps(late))
        record = collect_flow_result(self.root, self.flow, self.run_root)
        (detail,) = record["tests_detail"]
        self.assertEqual((detail["status"], detail["reason"]), ("ERROR", reason))
        self.assertEqual(detail["duration_sec"], 12.5)
        self.assertEqual(record["junit_xml"], {"total": 1, "missing": 0})

    def test_a_formal_regression_leaf_bucket_counts_once(self):
        formal = {"kind": "formal_fail", "signature": "assert_p", "count": 1}
        result_path = self.run_root / "result.json"
        result = json.loads(result_path.read_text())
        result["stages"].append(
            {"name": "formal", "item": "t_alpha", "status": "FAIL", "failure_buckets": [formal]}
        )
        result_path.write_text(json.dumps(result))
        regression_path = self.run_root / "stages" / "regress" / "regression.json"
        regression = json.loads(regression_path.read_text())
        regression["failure_buckets"].append({**formal, "affected": ["t_alpha"]})
        regression_path.write_text(json.dumps(regression))
        record = collect_flow_result(self.root, self.flow, self.run_root)
        counts = {bucket["kind"]: bucket["count"] for bucket in record["failure_buckets"]}
        self.assertEqual(counts, {"environment_error": 1, "formal_fail": 1})


if __name__ == "__main__":
    unittest.main()
