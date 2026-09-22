# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The frozen key set of every JSON file the runner and the coverage stages write.

Each constant below is one file or one record inside it. A file may carry exactly the
required keys plus any subset of its optional keys, and nothing else. A key enters or leaves
a set here only together with its readers, and with the schema version when a reader can no
longer consume the file. The published dashboard files are pinned the same way in
test_dashboard_schema and test_dashboard_links, the checkpoint and scheduler records in
test_cluster_executor, and the fields the documentation site reads in
test_dashboard_site_data.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.results import fragment_payload, rollup_payload  # noqa: E402
from test_coverage_closure import REGRESSION_REL, finish_run  # noqa: E402
from test_dashboard_schema import (  # noqa: E402
    FAILED_TEST_FIELDS,
    FLAKY_TEST_FIELDS,
    HOLES_SUMMARY_FIELDS,
    JUNIT_FIELDS,
    RECORD_COVERAGE_FIELDS,
    REGRESSION_FIELDS,
    RESULT_FIELDS,
    RESULT_OPTIONAL_FIELDS,
    RUN_METADATA_FIELDS,
    TEST_DETAIL_FIELDS,
)
from test_dashboard_site_data import (  # noqa: E402
    PASSING,
    RETRIED,
    STARTED,
    SiteDataCase,
    leaf_result,
)
from test_results_completion import TOOL  # noqa: E402

# -- run-level result.json --------------------------------------------------------------------
RESULT_KEYS = {
    "coverage",
    "description",
    "dry_run",
    "executor",
    "exit_code",
    "flow",
    "framework",
    "generated_at",
    "git",
    "items",
    "kind",
    "label",
    "license",
    "overrides",
    "run_dir",
    "runnability",
    "schema_version",
    "stages",
    "status",
    "tests",
    "tool",
    "tool_version",
    "tool_versions",
    "visibility",
}
RESULT_OPTIONAL_KEYS = {
    "targets",
    "formal",
    "overlay",
    "overlay_env",
    "site",
    "selection",
    "progress",
    "interruption",
}
RESULT_TESTS_KEYS = {
    "completed",
    "expected_failing",
    "failing",
    "leaves_planned",
    "leaves_run",
    "pass_rate",
    "passing",
    "skipped",
    "total",
}
GIT_KEYS = {"branch", "commit", "dirty"}
GIT_OPTIONAL_KEYS = {"diff_archive", "dirty_files"}
RESULT_COVERAGE_KEYS = {
    "backend",
    "build_fingerprint",
    "comparison_key",
    "coverage_details",
    "coverage_details_raw",
    "coverage_tool_version",
    "details_available",
    "effective_metrics",
    "enabled",
    "holes_summary",
    "manifest",
    "merged",
    "metrics",
    "parser",
    "policy_application",
    "policy_fingerprint",
    "policy_thresholds",
    "raw_metrics",
    "report",
    "scope_fingerprint",
    "status",
    "summary",
    "supported_metrics",
    "target",
    "threshold",
    "threshold_met",
    "total_percent",
}
HOLES_COUNT_KEYS = {
    "accepted",
    "by_category",
    "by_disposition",
    "by_metric",
    "by_status",
    "details_available",
    "hole_group_count",
    "native_point_count",
    "observations_complete",
    "open",
    "unclassified",
}
HOLES_SAMPLE_KEYS = {"samples", "sample_truncated"}
LEAF_STAGE_KEYS = {
    "duration_sec",
    "ended_at",
    "failure_buckets",
    "item",
    "log",
    "metadata",
    "name",
    "reason",
    "result_json",
    "return_code",
    "started_at",
    "status",
    "target",
}
LEAF_STAGE_OPTIONAL_KEYS = {"artifacts", "formal"}
LEAF_STAGE_METADATA_KEYS = {"attempt", "debug_only", "seed"}
LEAF_STAGE_METADATA_OPTIONAL_KEYS = {"scheduler", "wave_debug"}
RUN_STAGE_KEYS = {
    "artifacts",
    "duration_sec",
    "ended_at",
    "failure_buckets",
    "item",
    "log",
    "metadata",
    "name",
    "parser",
    "reason",
    "return_code",
    "started_at",
    "status",
}
RUN_STAGE_OPTIONAL_KEYS = {"target", "formal"}

# -- stages/regress/regression.json -----------------------------------------------------------
REGRESSION_KEYS = {
    "artifact_root",
    "artifacts",
    "duration_sec",
    "executor",
    "exit_code",
    "failed_tests",
    "failure_buckets",
    "flaky_tests",
    "flow",
    "framework",
    "generated_at",
    "git",
    "jobs",
    "kind",
    "license",
    "overrides",
    "producer",
    "rerun_commands",
    "run_dir",
    "runnability",
    "schema_version",
    "selection",
    "status",
    "tests",
    "tool",
    "tool_version",
    "tool_versions",
    "visibility",
}
REGRESSION_OPTIONAL_KEYS = {"progress", "interruption", "formal", "overlay", "overlay_env", "site"}
REGRESSION_TESTS_KEYS = RESULT_TESTS_KEYS | {"flaky"}
SELECTION_KEYS = {
    "allow_duplicates",
    "expanded_count",
    "expanded_items",
    "max_failures",
    "requested_items",
    "reseed",
    "retry",
    "run_mode",
    "stages",
    "tags",
}
JOB_KEYS = {
    "attempt",
    "duration_sec",
    "ended_at",
    "failure_buckets",
    "item",
    "log",
    "metadata",
    "reason",
    "result_json",
    "return_code",
    "seed",
    "stage",
    "started_at",
    "status",
    "target",
}
JOB_OPTIONAL_KEYS = {"artifacts", "formal", "wave_debug"}
FAILED_TEST_KEYS = {
    "attempt_count",
    "attempts",
    "duration_sec",
    "failure_buckets",
    "item",
    "log",
    "reason",
    "rerun",
    "result_json",
    "seed",
    "status",
    "target",
}
FAILED_TEST_OPTIONAL_KEYS = {"expected_fail", "wave_debug", "wave_replay"}
ATTEMPT_KEYS = {
    "attempt",
    "duration_sec",
    "failure_buckets",
    "log",
    "reason",
    "result_json",
    "return_code",
    "status",
}
ATTEMPT_OPTIONAL_KEYS = {"wave_debug"}
FLAKY_TEST_KEYS = {
    "attempt_count",
    "attempts",
    "failing_attempts",
    "final_status",
    "first_fail_attempt",
    "first_failure_reason",
    "flaky",
    "flaky_reason",
    "item",
    "log",
    "passed_on_attempt",
    "rerun",
    "result_json",
    "seed",
    "target",
}
FAILURE_BUCKET_KEYS = {"affected", "count", "examples", "kind", "signature"}
FAILURE_BUCKET_OPTIONAL_KEYS = {"reason"}
AFFECTED_KEYS = {"item", "seed", "status", "target"}
INTERRUPTION_KEYS = {"kind", "reason", "recorded_at"}
INTERRUPTION_OPTIONAL_KEYS = {"signal", "signal_number", "executor", "cancellation"}

# -- the leaf and per-test records ------------------------------------------------------------
LEAF_RECORD_KEYS = {
    "artifacts",
    "attempt",
    "duration_sec",
    "ended_at",
    "exit_code",
    "failure_buckets",
    "flow",
    "framework",
    "item",
    "kind",
    "log",
    "metadata",
    "parser",
    "reason",
    "return_code",
    "run_dir",
    "schema_version",
    "seed",
    "started_at",
    "status",
    "target",
    "target_build",
    "tool",
}
LEAF_RECORD_OPTIONAL_KEYS = {"formal"}
ROLLUP_KEYS = {
    "exit_code",
    "flow",
    "item",
    "run_dir",
    "runs",
    "schema_version",
    "status",
    "target",
    "tests",
    "tool",
}
ROLLUP_OPTIONAL_KEYS = {"formal"}
ROLLUP_RUN_KEYS = {"artifacts", "log", "reason", "seed", "status"}
ROLLUP_TESTS_KEYS = {"expected_failing", "failing", "pass_rate", "passing", "skipped", "total"}

# -- the coverage files -------------------------------------------------------------------------
MANIFEST_KEYS = {
    "artifacts",
    "backend",
    "build_fingerprint",
    "comparison_key",
    "dut",
    "exclusions",
    "generated_at",
    "holes_summary",
    "inputs",
    "merge_return_code",
    "metrics",
    "overall_percent",
    "parser",
    "policy",
    "policy_fingerprint",
    "policy_thresholds",
    "rejected",
    "report_return_code",
    "schema_version",
    "scope_fingerprint",
    "selection_policy",
    "selection_source",
    "status",
    "supported_metrics",
    "target",
    "threshold",
    "threshold_met",
    "tool",
    "tool_version",
    "waivers",
}
MANIFEST_OPTIONAL_KEYS = {"combine"}
MANIFEST_INPUT_KEYS = {
    "attempt",
    "build_fingerprint",
    "item",
    "path",
    "result_json",
    "seed",
    "source",
    "status",
    "target",
}
MANIFEST_ARTIFACT_KEYS = {
    "coverage_details",
    "coverage_details_raw",
    "merged",
    "policy_application",
    "report",
    "summary",
}
MANIFEST_ARTIFACT_OPTIONAL_KEYS = {"report_raw", "design_db"}
MANIFEST_POLICY_KEYS = {
    "legacy_exclusions",
    "legacy_waivers",
    "native_files",
    "path",
    "scope_epoch",
    "sha256",
}
REPORT_SUMMARY_KEYS = {
    "artifacts",
    "backend",
    "comparison_key",
    "compatibility_threshold_met",
    "details_available",
    "dut",
    "holes_summary",
    "inputs",
    "metrics",
    "overall_percent",
    "policy_fingerprint",
    "policy_thresholds",
    "schema_version",
    "scope_fingerprint",
    "status",
    "supported_metrics",
    "threshold",
    "threshold_met",
    "tool",
    "tool_versions",
}
REPORT_SUMMARY_ARTIFACT_KEYS = {
    "coverage_details",
    "coverage_details_raw",
    "json",
    "manifest",
    "merged",
    "policy_application",
    "report",
}
THRESHOLD_OUTCOME_KEYS = {
    "actual_percent",
    "id",
    "max_unclassified_points",
    "met",
    "metric_family",
    "minimum_percent",
    "population",
    "scope",
    "unclassified_points",
}
DETAILS_KEYS = {
    "build_fingerprint",
    "comparison_key",
    "details_available",
    "dut",
    "holes_summary",
    "metrics",
    "observations",
    "policy_application",
    "policy_fingerprint",
    "schema_version",
    "scope_fingerprint",
    "target",
    "thresholds",
    "tool",
    "warnings",
}
DETAILS_METRIC_KEYS = {
    "available",
    "covered",
    "effective_percent",
    "excluded",
    "metric_family",
    "native_metric",
    "raw_percent",
    "total",
}
OBSERVATION_KEYS = {
    "category",
    "confidence",
    "count",
    "covered",
    "disposition",
    "goal",
    "hierarchy",
    "id",
    "issues",
    "line",
    "metric_family",
    "native_locator",
    "native_metric",
    "owner",
    "policy_id",
    "rationale",
    "reviewer",
    "source",
    "status",
    "tool",
}
APPLICATION_KEYS = {"matched", "native_files", "policy", "policy_sha256", "warnings"}
MATCHED_KEYS = {"observation_ids", "policy_id"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def named(stages: Iterable[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(stage for stage in stages if stage["name"] == name)


class ContractCase(unittest.TestCase):
    def assert_keys(
        self,
        record: Any,
        required: set[str],
        optional: frozenset[str] | set[str] = frozenset(),
        *,
        where: str,
    ) -> None:
        """`record` carries every required key and no key outside required and optional."""
        self.assertIsInstance(record, dict, where)
        keys = set(record)
        self.assertEqual(required - keys, set(), f"{where}: missing")
        self.assertEqual(keys - required - optional, set(), f"{where}: unexpected")


class RunLevelFiles(SiteDataCase, ContractCase):
    def test_result_json_of_a_regression_with_coverage(self):
        self.write_run(PASSING, coverage=True)
        result = read_json(self.run_dir / "result.json")
        self.assert_keys(result, RESULT_KEYS, RESULT_OPTIONAL_KEYS, where="result.json")
        self.assert_keys(result["tests"], RESULT_TESTS_KEYS, where="result.json tests")
        self.assert_keys(result["git"], GIT_KEYS, GIT_OPTIONAL_KEYS, where="result.json git")
        self.assert_keys(result["coverage"], RESULT_COVERAGE_KEYS, where="result.json coverage")
        self.assert_keys(
            result["coverage"]["holes_summary"], HOLES_COUNT_KEYS, where="result.json holes"
        )
        sim = named(result["stages"], "sim")
        self.assert_keys(sim, LEAF_STAGE_KEYS, LEAF_STAGE_OPTIONAL_KEYS, where="leaf stage")
        self.assert_keys(
            sim["metadata"],
            LEAF_STAGE_METADATA_KEYS,
            LEAF_STAGE_METADATA_OPTIONAL_KEYS,
            where="leaf stage metadata",
        )
        self.assertTrue(sim["result_json"].endswith("/attempt_0/result.json"))
        for name in ("cov_merge", "cov_report"):
            self.assert_keys(
                named(result["stages"], name), RUN_STAGE_KEYS, RUN_STAGE_OPTIONAL_KEYS, where=name
            )

    def test_result_json_without_coverage_keeps_the_same_coverage_keys(self):
        self.write_run(RETRIED)
        coverage = read_json(self.run_dir / "result.json")["coverage"]
        self.assert_keys(coverage, RESULT_COVERAGE_KEYS, where="result.json coverage (SKIP)")
        self.assertEqual(set(coverage["holes_summary"]), {"details_available"})

    def test_regression_json(self):
        self.write_run(RETRIED)
        regression = read_json(self.run_dir / "stages" / "regress" / "regression.json")
        self.assert_keys(
            regression, REGRESSION_KEYS, REGRESSION_OPTIONAL_KEYS, where="regression.json"
        )
        self.assert_keys(regression["tests"], REGRESSION_TESTS_KEYS, where="regression tests")
        self.assert_keys(regression["selection"], SELECTION_KEYS, where="regression selection")
        for job in regression["jobs"]:
            self.assert_keys(job, JOB_KEYS, JOB_OPTIONAL_KEYS, where="job")
            self.assert_keys(
                job["metadata"],
                LEAF_STAGE_METADATA_KEYS,
                LEAF_STAGE_METADATA_OPTIONAL_KEYS,
                where="job metadata",
            )
        (failed,) = regression["failed_tests"]
        self.assert_keys(failed, FAILED_TEST_KEYS, FAILED_TEST_OPTIONAL_KEYS, where="failed test")
        for attempt in failed["attempts"]:
            self.assert_keys(attempt, ATTEMPT_KEYS, ATTEMPT_OPTIONAL_KEYS, where="attempt")
        (flaky,) = regression["flaky_tests"]
        self.assert_keys(flaky, FLAKY_TEST_KEYS, where="flaky test")
        for attempt in flaky["attempts"]:
            self.assert_keys(attempt, ATTEMPT_KEYS, ATTEMPT_OPTIONAL_KEYS, where="flaky attempt")
        for bucket in regression["failure_buckets"]:
            self.assert_keys(
                bucket, FAILURE_BUCKET_KEYS, FAILURE_BUCKET_OPTIONAL_KEYS, where="bucket"
            )
            for affected in bucket["affected"]:
                self.assert_keys(affected, AFFECTED_KEYS, where="affected leaf")

    def test_an_interrupted_run_adds_progress_and_interruption(self):
        self.write_run(STARTED, interrupted=True)
        result = read_json(self.run_dir / "result.json")
        self.assert_keys(result, RESULT_KEYS, RESULT_OPTIONAL_KEYS, where="result.json")
        self.assertIn("progress", result)
        self.assert_keys(
            result["interruption"],
            INTERRUPTION_KEYS,
            INTERRUPTION_OPTIONAL_KEYS,
            where="interruption",
        )
        regression = read_json(self.run_dir / REGRESSION_REL)
        self.assertEqual(regression["interruption"], result["interruption"])
        bucket = regression["failure_buckets"][-1]
        self.assertEqual(bucket["kind"], "interruption")
        self.assert_keys(bucket, FAILURE_BUCKET_KEYS, where="interruption bucket")


class LeafAndRollupRecords(SiteDataCase, ContractCase):
    def test_leaf_record(self):
        result = leaf_result(PASSING[0])
        result.metadata = {
            **(result.metadata or {}),
            "target": "default",
            "target_build": {"target": "default", "fingerprint": "fp"},
        }
        leaf = fragment_payload(
            flow=self.flow,
            root=self.root,
            tool=TOOL,
            run_dir=self.run_dir,
            item=PASSING[0].item,
            seed=PASSING[0].seed,
            result=result,
        )
        self.assert_keys(leaf, LEAF_RECORD_KEYS, LEAF_RECORD_OPTIONAL_KEYS, where="leaf record")
        self.assertEqual(leaf["target_build"]["target"], "default")
        self.assertNotIn("target_build", leaf["metadata"])

    def test_rollup_record(self):
        rollup = rollup_payload(
            flow=self.flow,
            root=self.root,
            tool=TOOL,
            run_dir=self.run_dir,
            item=PASSING[0].item,
            runs=[(PASSING[0].seed, leaf_result(PASSING[0]))],
        )
        self.assert_keys(rollup, ROLLUP_KEYS, ROLLUP_OPTIONAL_KEYS, where="rollup")
        self.assert_keys(rollup["tests"], ROLLUP_TESTS_KEYS, where="rollup tests")
        for run in rollup["runs"]:
            self.assert_keys(run, ROLLUP_RUN_KEYS, where="rollup run")


# Staging a coverage report into the bundle keeps each rewritten path's original value.
STAGED_SOURCE_KEYS = {
    "source_manifest",
    "source_policy_application",
    "source_report",
    "source_summary",
}


class PublishedRecord(SiteDataCase, ContractCase):
    """The collector's record, as the dashboard and the archive read it."""

    def assert_record(self, record: dict[str, Any], holes: set[str]) -> None:
        self.assert_keys(record, RESULT_FIELDS, RESULT_OPTIONAL_FIELDS, where="published record")
        self.assert_keys(
            record["coverage"],
            RECORD_COVERAGE_FIELDS,
            STAGED_SOURCE_KEYS,
            where="published coverage",
        )
        self.assert_keys(record["coverage"]["holes_summary"], holes, where="published holes")
        self.assert_keys(record["run_metadata"], RUN_METADATA_FIELDS, where="run_metadata")
        self.assert_keys(record["junit_xml"], JUNIT_FIELDS, where="junit_xml")
        self.assert_keys(record["regression"], REGRESSION_FIELDS, where="published regression")
        for test in record["tests_detail"]:
            self.assert_keys(test, TEST_DETAIL_FIELDS, where="tests_detail entry")
        for entry in record["regression"]["failed_tests"]:
            self.assert_keys(entry, FAILED_TEST_FIELDS, where="published failed test")
        for entry in record["regression"]["flaky_tests"]:
            self.assert_keys(entry, FLAKY_TEST_FIELDS, where="published flaky test")

    def test_record_of_a_run_with_coverage(self):
        self.write_run(PASSING, coverage=True)
        record, _, _, _ = self.publish()
        self.assert_record(record, HOLES_SUMMARY_FIELDS)

    def test_record_of_a_run_without_coverage(self):
        self.write_run(RETRIED)
        record, _, _, _ = self.publish()
        self.assert_record(record, {"details_available"})
        self.assertEqual(len(record["regression"]["failed_tests"]), 1)
        self.assertEqual(len(record["regression"]["flaky_tests"]), 1)


class CoverageFiles(ContractCase):
    """The report stage's own files, produced by the closure fixture's graded run."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = finish_run(self.root)
        self.report = self.run_dir / "cov" / "report"

    def test_manifest(self):
        manifest = read_json(self.run_dir / "cov" / "coverage.json")
        self.assert_keys(manifest, MANIFEST_KEYS, MANIFEST_OPTIONAL_KEYS, where="coverage.json")
        self.assert_keys(manifest["holes_summary"], HOLES_COUNT_KEYS, where="manifest holes")
        self.assert_keys(
            manifest["artifacts"],
            MANIFEST_ARTIFACT_KEYS,
            MANIFEST_ARTIFACT_OPTIONAL_KEYS,
            where="manifest artifacts",
        )
        self.assert_keys(manifest["policy"], MANIFEST_POLICY_KEYS, where="manifest policy")
        for entry in manifest["inputs"]:
            self.assert_keys(entry, MANIFEST_INPUT_KEYS, where="manifest input")

    def test_report_summary_is_the_one_file_with_hole_samples(self):
        summary = read_json(self.report / "summary.json")
        self.assert_keys(summary, REPORT_SUMMARY_KEYS, where="summary.json")
        self.assert_keys(
            summary["holes_summary"], HOLES_COUNT_KEYS | HOLES_SAMPLE_KEYS, where="summary holes"
        )
        self.assert_keys(summary["artifacts"], REPORT_SUMMARY_ARTIFACT_KEYS, where="summary paths")
        for outcome in summary["policy_thresholds"]:
            self.assert_keys(outcome, THRESHOLD_OUTCOME_KEYS, where="threshold outcome")
        for sample in summary["holes_summary"]["samples"]:
            self.assert_keys(sample, OBSERVATION_KEYS, where="sample hole")

    def test_details_and_policy_application(self):
        details = read_json(self.report / "coverage-details.json")
        self.assert_keys(details, DETAILS_KEYS, where="coverage-details.json")
        for metric in details["metrics"]:
            self.assert_keys(metric, DETAILS_METRIC_KEYS, where="details metric")
        for observation in details["observations"]:
            self.assert_keys(observation, OBSERVATION_KEYS, where="observation")
        application = read_json(self.report / "policy-application.json")
        self.assert_keys(application, APPLICATION_KEYS, where="policy-application.json")
        for match in application["matched"]:
            self.assert_keys(match, MATCHED_KEYS, where="matched entry")

    def test_run_record_carries_the_graded_counts(self):
        result = read_json(self.run_dir / "result.json")
        self.assert_keys(result["coverage"], RESULT_COVERAGE_KEYS, where="graded coverage")
        self.assert_keys(
            result["coverage"]["holes_summary"], HOLES_COUNT_KEYS, where="graded holes"
        )
        self.assertNotIn("coverage", read_json(self.run_dir / REGRESSION_REL))


if __name__ == "__main__":
    unittest.main()
