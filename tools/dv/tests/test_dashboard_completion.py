# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for run-completion accounting in the dashboard pipeline.

A collected record keeps the runner's `tests.completed`, publishes no pass rate for a run
that did not finish, and stays out of the cross-DUT test counters.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.collect_results import _collect_native_result  # noqa: E402
from dashboard.gen_dashboard import _dut_rows, _status_cards, render_dashboard  # noqa: E402
from dashboard.gen_report import render_report  # noqa: E402
from dashboard.schema import (  # noqa: E402
    _category_summary,
    _dut_status,
    make_result,
    make_summary,
    run_completed,
)
from runlib.results import result_payload, write_result  # noqa: E402
from test_dashboard_schema import TEST_DETAIL_FIELDS  # noqa: E402
from test_results_completion import (  # noqa: E402
    INTERRUPTION,
    ITEMS,
    TOOL,
    interrupted_progress,
    leaf,
    make_flow,
)


class DashboardCompletion(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "dut" / "build" / "runs" / "r"
        self.run_dir.mkdir(parents=True)
        self.flow = make_flow(self.root)

    def record(self, *, completed, total, passing, flow="fixture", status="FAIL", detail=None):
        return make_result(
            repo_root=self.root,
            flow=flow,
            kind="sim",
            status=status,
            tool=TOOL,
            tests_total=total,
            tests_passing=passing,
            tests_completed=completed,
            tests_detail=detail,
        )

    def collect_interrupted_run(self) -> dict:
        payload = result_payload(
            flow=self.flow,
            root=self.root,
            tool=TOOL,
            run_dir=self.run_dir,
            stages=[leaf("t_alpha")],
            dry_run=False,
            items=ITEMS,
            args=Namespace(dry_run=False, verbose=False, quiet=True, cov=False),
            status_override="ERROR",
            progress=interrupted_progress(3, 1),
            interruption=INTERRUPTION,
            versions={TOOL: "5.0"},
            git_metadata={},
            planned_leaves=3,
        )
        write_result(self.run_dir / "result.json", payload)
        record = _collect_native_result(self.root, self.flow, self.run_dir)
        self.assertIsNotNone(record)
        return record

    def test_result_record_publishes_no_rate_for_an_incomplete_run(self):
        tests = self.record(completed=False, total=1, passing=1)["tests"]
        self.assertFalse(tests["completed"])
        self.assertIsNone(tests["pass_rate"])
        self.assertEqual((tests["total"], tests["passing"]), (1, 1))

    def test_result_record_keeps_the_rate_when_completion_is_known_or_unrecorded(self):
        self.assertEqual(
            self.record(completed=True, total=4, passing=3)["tests"]["pass_rate"], 75.0
        )
        legacy = self.record(completed=None, total=4, passing=3)
        self.assertEqual(legacy["tests"]["pass_rate"], 75.0)
        self.assertIsNone(legacy["tests"]["completed"])
        self.assertIsNone(run_completed(legacy))
        self.assertIsNone(run_completed({"status": "PASS", "tests": {"pass_rate": 1.0}}))

    def test_collector_carries_the_runner_completion(self):
        record = self.collect_interrupted_run()
        self.assertEqual(record["status"], "FAIL")
        self.assertFalse(record["tests"]["completed"])
        self.assertIsNone(record["tests"]["pass_rate"])
        self.assertEqual(record["tests"]["passing"], 1)
        self.assertEqual([set(test) for test in record["tests_detail"]], [TEST_DETAIL_FIELDS])
        self.assertIn("incomplete run", render_report(record))

    def test_summary_leaves_incomplete_runs_out_of_the_test_counters(self):
        complete = self.record(
            completed=True,
            total=10,
            passing=9,
            flow="alpha",
            detail=[{"name": "a", "status": "PASS", "category": "smoke"}],
        )
        incomplete = self.record(
            completed=False,
            total=1,
            passing=1,
            flow="beta",
            detail=[{"name": "b", "status": "PASS", "category": "smoke"}],
        )
        summary = make_summary([complete, incomplete])
        tests = summary["tests"]
        self.assertEqual((tests["total"], tests["passing"], tests["pass_rate"]), (10, 9, 90.0))
        self.assertEqual(tests["incomplete_runs"], 1)
        self.assertEqual((summary["flows"]["total"], summary["flows"]["failing"]), (2, 2))
        categories = _category_summary([complete, incomplete])
        self.assertEqual([(c["category"], c["total"]) for c in categories], [("smoke", 1)])
        rows = {row["flow"]: row for row in _dut_status([complete, incomplete])}
        self.assertFalse(rows["beta"]["tests_completed"])
        self.assertIsNone(rows["beta"]["pass_rate"])
        self.assertTrue(rows["alpha"]["tests_completed"])
        self.assertEqual(rows["alpha"]["pass_rate"], 90.0)

    def test_summary_without_incomplete_runs_is_unchanged(self):
        summary = make_summary([self.record(completed=None, total=4, passing=4, status="PASS")])
        self.assertEqual(summary["tests"]["pass_rate"], 100.0)
        self.assertEqual(summary["tests"]["incomplete_runs"], 0)
        self.assertNotIn("incomplete", _status_cards(summary))

    def test_the_flow_card_names_the_skipped_flows(self):
        passed = self.record(completed=True, total=4, passing=4, flow="alpha", status="PASS")
        skipped = self.record(completed=True, total=0, passing=0, flow="beta", status="SKIP")
        self.assertIn("1 / 2 passing; 1 skipped", _status_cards(make_summary([passed, skipped])))
        self.assertNotIn("skipped", _status_cards(make_summary([passed])))

    def test_html_marks_the_incomplete_run(self):
        record = self.collect_interrupted_run()
        summary = make_summary([record])
        summary["dut_status"] = _dut_status([record])
        summary["results"] = [record]
        self.assertIn("incomplete run", _dut_rows(summary))
        self.assertIn("1 incomplete run(s) excluded", _status_cards(summary))
        self.assertIn("incomplete run", render_dashboard(summary))


if __name__ == "__main__":
    unittest.main()
