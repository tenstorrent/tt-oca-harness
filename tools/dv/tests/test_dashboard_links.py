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


if __name__ == "__main__":
    unittest.main()
