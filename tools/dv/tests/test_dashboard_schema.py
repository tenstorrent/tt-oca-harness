# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the normalized dashboard JSON contract.

The field sets below are the ones the JSON field reference of the dashboard guide lists.
The documentation site under tools/doc reads a subset of them; a field that moves or vanishes
fails here before it fails on the published branch.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "doc"))

import trim_dashboard_data as trim  # noqa: E402
from dashboard.publish_reports import write_manifest  # noqa: E402
from dashboard.schema import (  # noqa: E402
    SCHEMA_VERSION,
    make_result,
    make_summary,
    make_trend_point,
    update_history,
)
from test_results_completion import TOOL  # noqa: E402

RESULT_FIELDS = {
    "schema_version",
    "generated_at",
    "flow",
    "kind",
    "tool",
    "framework",
    "status",
    "git",
    "timing",
    "tests",
    "coverage",
    "artifacts",
    "failure_buckets",
    "source",
}
RESULT_OPTIONAL_FIELDS = {"run_metadata", "tests_detail", "junit_xml", "regression", "warnings"}
TESTS_FIELDS = {"total", "passing", "failing", "completed", "pass_rate"}
SUMMARY_FIELDS = {
    "schema_version",
    "generated_at",
    "flows",
    "tests",
    "coverage",
    "coverage_closure",
    "regression",
    "junit_xml",
    "warnings",
    "dut_status",
    "categories",
    "failure_buckets",
    "results",
}
DUT_STATUS_FIELDS = {
    "flow",
    "kind",
    "framework",
    "tool",
    "status",
    "tests_total",
    "tests_passing",
    "tests_failing",
    "tests_skipped",
    "tests_unknown",
    "tests_completed",
    "pass_rate",
    "category_count",
    "categories",
    "failed_tests",
    "flaky_tests",
    "coverage_total_percent",
    "coverage_status",
    "coverage_threshold",
    "coverage_threshold_met",
    "coverage_details_available",
    "coverage_open_holes",
    "coverage_accepted_holes",
    "coverage_unclassified_holes",
    "coverage_comparison_key",
    "report",
    "run_dir",
}
BY_DUT_FIELDS = {
    "dut",
    "framework",
    "tool",
    "details_available",
    "open",
    "accepted",
    "unclassified",
    "native_point_count",
    "hole_group_count",
    "threshold_failures",
    "comparison_key",
}
POINT_FIELDS = {
    "id",
    "generated_at",
    "flow_pass_rate",
    "test_pass_rate",
    "failed_tests",
    "flaky_tests",
    "per_dut",
}
PER_DUT_FIELDS = {
    "flow",
    "framework",
    "tool",
    "target",
    "comparison_key",
    "status",
    "coverage_status",
    "threshold_met",
    "raw_metrics",
    "effective_metrics",
    "holes_summary",
}
MANIFEST_FIELDS = {
    "schema_version",
    "generated_at",
    "publish_name",
    "timestamp",
    "source",
    "source_result_files",
    "output_files",
}
TEST_DETAIL_FIELDS = {
    "name",
    "category",
    "seed",
    "attempt",
    "stage",
    "status",
    "duration_sec",
    "reason",
}
RECORD_COVERAGE_FIELDS = {
    "status",
    "total_percent",
    "threshold",
    "threshold_met",
    "details_available",
    "comparison_key",
    "target",
    "policy_thresholds",
    "raw_metrics",
    "effective_metrics",
    "holes_summary",
    "report",
    "summary",
    "manifest",
    "policy_application",
}
HOLES_SUMMARY_FIELDS = {
    "details_available",
    "observations_complete",
    "native_point_count",
    "hole_group_count",
    "open",
    "accepted",
    "unclassified",
    "by_metric",
    "by_category",
    "by_disposition",
    "by_status",
}
REGRESSION_FIELDS = {"failed_tests", "flaky_tests"}
FAILED_TEST_FIELDS = {"item", "seed", "status", "reason", "rerun"}
FLAKY_TEST_FIELDS = {"item", "seed", "final_status", "attempt_count", "rerun"}
RUN_METADATA_FIELDS = {
    "run_dir",
    "result_json",
    "label",
    "tool",
    "tool_version",
    "executor",
    "generated_at",
    "git",
}
JUNIT_FIELDS = {"total", "missing"}
DUTS = ("cross_trigger_port", "dtp", "sep", "smc")


class ContractCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def record(self, flow, status="PASS", *, run_id="42", coverage=None, **extra):
        return make_result(
            repo_root=self.root,
            flow=flow,
            kind="sim",
            status=status,
            tool=TOOL,
            framework="cocotb",
            tests_total=4,
            tests_passing=4 if status == "PASS" else 3,
            tests_completed=True,
            coverage_details=coverage or {},
            artifacts={"run_dir": f"build/ci/runs/{flow}/{TOOL}/weekly/{run_id}"},
            **extra,
        )

    def records(self, statuses=("PASS", "PASS", "FAIL", "PASS"), **kwargs):
        return [self.record(flow, status, **kwargs) for flow, status in zip(DUTS, statuses)]


class NormalizedRecord(ContractCase):
    def test_record_carries_the_documented_fields(self):
        self.assertEqual(set(self.record("dtp")), RESULT_FIELDS)
        full = self.record(
            "dtp",
            run_metadata={"run_dir": "x"},
            tests_detail=[],
            junit_xml={},
            regression={},
            warnings=["w"],
        )
        self.assertEqual(set(full), RESULT_FIELDS | RESULT_OPTIONAL_FIELDS)
        self.assertEqual(set(full["tests"]), TESTS_FIELDS)
        self.assertEqual(full["schema_version"], SCHEMA_VERSION)
        self.assertEqual(SCHEMA_VERSION, "0.2")

    def test_status_vocabulary_is_pass_fail_unknown(self):
        summary = make_summary(self.records(("PASS", "FAIL", "UNKNOWN", "PASS")))
        self.assertEqual(
            {row["status"] for row in summary["dut_status"]}, {"PASS", "FAIL", "UNKNOWN"}
        )
        self.assertEqual(
            (summary["flows"]["passing"], summary["flows"]["failing"], summary["flows"]["unknown"]),
            (2, 1, 1),
        )


class AggregateSummary(ContractCase):
    def test_summary_carries_the_documented_fields(self):
        summary = make_summary(self.records())
        self.assertEqual(set(summary), SUMMARY_FIELDS)
        self.assertEqual(summary["schema_version"], "0.2")
        for row in summary["dut_status"]:
            self.assertEqual(set(row), DUT_STATUS_FIELDS)
        for row in summary["coverage_closure"]["by_dut"]:
            self.assertEqual(set(row), BY_DUT_FIELDS)

    def test_every_record_is_one_row_keyed_by_dut(self):
        summary = make_summary(self.records())
        self.assertEqual(summary["flows"]["total"], len(DUTS))
        self.assertEqual([row["flow"] for row in summary["dut_status"]], sorted(DUTS))
        self.assertEqual(
            [row["framework"] for row in summary["dut_status"]], ["cocotb"] * len(DUTS)
        )
        self.assertEqual(
            [row["dut"] for row in summary["coverage_closure"]["by_dut"]], sorted(DUTS)
        )
        self.assertEqual([result["flow"] for result in summary["results"]], list(DUTS))

    def test_a_missing_dut_changes_the_flow_count(self):
        summary = make_summary(self.records()[:-1])
        self.assertEqual(summary["flows"]["total"], len(DUTS) - 1)


class TrendHistory(ContractCase):
    def test_point_carries_the_documented_fields(self):
        point = make_trend_point(make_summary(self.records()))
        self.assertEqual(set(point), POINT_FIELDS)
        self.assertEqual(len(point["per_dut"]), len(DUTS))
        for entry in point["per_dut"]:
            self.assertEqual(set(entry), PER_DUT_FIELDS)
        self.assertEqual([entry["flow"] for entry in point["per_dut"]], list(DUTS))

    def test_identity_follows_the_dut_set_and_the_run(self):
        same = make_trend_point(make_summary(self.records()))["id"]
        self.assertEqual(same, make_trend_point(make_summary(self.records()))["id"])
        fewer = make_trend_point(make_summary(self.records()[:-1]))["id"]
        other_run = make_trend_point(make_summary(self.records(run_id="43")))["id"]
        self.assertNotEqual(same, fewer)
        self.assertNotEqual(same, other_run)
        self.assertEqual(len(same), 16)

    def test_update_replaces_the_point_of_identical_inputs_only(self):
        first = update_history(None, make_summary(self.records()))
        again = update_history(first, make_summary(self.records()))
        grown = update_history(again, make_summary(self.records(run_id="43")))
        self.assertEqual(first["schema_version"], "0.2")
        self.assertEqual(len(again["points"]), 1)
        self.assertEqual(len(grown["points"]), 2)
        self.assertEqual(
            [len(point["per_dut"]) for point in grown["points"]], [len(DUTS), len(DUTS)]
        )


class PublicationManifest(ContractCase):
    def test_manifest_carries_the_documented_fields(self):
        source = self.root / "bundle"
        source.mkdir()
        results = self.records()
        for result in results:
            result["artifacts"]["result_json"] = f"bundle/{result['flow']}.result.json"
            (source / f"{result['flow']}.result.json").write_text(json.dumps(result))
        (source / "summary.json").write_text(json.dumps(make_summary(results)))
        manifest = json.loads(write_manifest(source, "dv", "20260919_000000").read_text())
        self.assertEqual(set(manifest), MANIFEST_FIELDS)
        self.assertEqual(manifest["schema_version"], "0.1")
        self.assertEqual(
            manifest["source_result_files"],
            sorted(f"bundle/{flow}.result.json" for flow in DUTS),
        )
        self.assertIn("summary.json", manifest["output_files"])


class DocumentationSiteConsumer(ContractCase):
    """tools/doc/trim_dashboard_data.py reads only fields the producer writes."""

    def test_trimmed_fields_are_produced(self):
        self.assertLessEqual(set(trim.SUMMARY_KEYS), SUMMARY_FIELDS)
        self.assertLessEqual(set(trim.DUT_KEYS), DUT_STATUS_FIELDS)
        self.assertLessEqual(set(trim.RESULT_KEYS), RESULT_FIELDS)
        self.assertLessEqual(set(trim.COVERAGE_KEYS), PER_DUT_FIELDS)
        self.assertLessEqual(set(trim.TEST_KEYS), TEST_DETAIL_FIELDS)
        self.assertLessEqual(set(trim.HISTORY_POINT_KEYS), POINT_FIELDS)
        self.assertLessEqual(set(trim.HISTORY_DUT_KEYS), PER_DUT_FIELDS)

    def test_trim_keeps_one_row_per_dut(self):
        summary = make_summary(self.records(coverage={"effective_metrics": {"line": 50.0}}))
        source = self.root / "summary.json"
        source.write_text(json.dumps(summary))
        output = self.root / "site" / "summary.json"
        rc = trim.trim_summary(Namespace(source=source, output=output, tests_out=None))
        self.assertEqual(rc, 0)
        trimmed = json.loads(output.read_text())
        self.assertEqual([row["flow"] for row in trimmed["dut_status"]], sorted(DUTS))
        self.assertEqual(set(trimmed["dut_status"][0]), set(trim.DUT_KEYS))
        self.assertEqual(
            [result["coverage"]["effective_metrics"] for result in trimmed["results"]],
            [{"line": 50.0}] * len(DUTS),
        )
        point = trim.trim_history_point(make_trend_point(summary))
        self.assertEqual(set(point), set(trim.HISTORY_POINT_KEYS) | {"per_dut"})
        self.assertEqual([entry["flow"] for entry in point["per_dut"]], list(DUTS))


if __name__ == "__main__":
    unittest.main()
