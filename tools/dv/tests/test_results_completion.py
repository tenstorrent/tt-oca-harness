# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for run-completion accounting in the result records.

A run that stopped before every planned leaf finished publishes no pass rate, says so in
`tests.completed`, and is refused by the coverage re-grade paths.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import io
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import _require_completed_run  # noqa: E402
from runlib.junit import materialize_interruption_junit  # noqa: E402
from runlib.models import ConfigError, Dut, StageResult  # noqa: E402
from runlib.results import (  # noqa: E402
    incomplete_run_note,
    regression_payload,
    result_payload,
    run_completion,
    run_is_complete,
)
from runlib.ui import Console  # noqa: E402

TOOL = "verilator"
ITEMS = ["t_alpha", "t_beta", "t_gamma"]


def make_flow(root: Path) -> Dut:
    return Dut(
        name="fixture",
        kind="sim",
        description="completion fixture",
        framework="cocotb",
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root="dut",
        default_tool=TOOL,
        tools=[TOOL],
        path=root / "dut" / "fixture_sim_cfg.toml",
        raw={},
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


def leaf(item: str, status: str = "PASS") -> StageResult:
    return StageResult(
        stage="sim",
        item=item,
        status=status,
        return_code=0 if status == "PASS" else 1,
        duration_sec=1.5,
        started_at="2026-09-01T00:00:00+00:00",
        ended_at="2026-09-01T00:00:01+00:00",
        log=f"dut/build/runs/r/{item}/seed_1/attempt_0/logs/sim.log",
        metadata={"seed": 1, "attempt": 0},
    )


def job(item: str, status: str = "PASS") -> dict:
    return {
        "stage": "sim",
        "item": item,
        "seed": 1,
        "attempt": 0,
        "status": status,
        "return_code": 0 if status == "PASS" else 1,
        "duration_sec": 1.5,
        "started_at": "2026-09-01T00:00:00+00:00",
        "ended_at": "2026-09-01T00:00:01+00:00",
    }


def interrupted_progress(expected: int, completed: int) -> dict:
    return {
        "state": "interrupted",
        "sequence": completed + 1,
        "updated_at": "2026-09-01T00:00:02+00:00",
        "expected_count": expected,
        "completed_count": completed,
        "active_count": 0,
        "missing_count": expected - completed - 1,
        "interrupted_count": 1,
        "expected": [],
        "completed": [],
        "active": [],
        "missing": [],
        "interrupted": [],
    }


INTERRUPTION = {
    "kind": "signal",
    "signal": "SIGTERM",
    "signal_number": 15,
    "reason": "run interrupted by SIGTERM",
    "recorded_at": "2026-09-01T00:00:02+00:00",
}


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "dut" / "build" / "runs" / "r"
        self.run_dir.mkdir(parents=True)
        self.flow = make_flow(self.root)
        self.args = Namespace(dry_run=False, verbose=False, quiet=True, cov=False)

    def result(self, stages, **kwargs) -> dict:
        return result_payload(
            flow=self.flow,
            root=self.root,
            tool=TOOL,
            run_dir=self.run_dir,
            stages=stages,
            dry_run=False,
            items=ITEMS,
            args=self.args,
            versions={TOOL: "5.0"},
            git_metadata={},
            **kwargs,
        )

    def regression(self, jobs, stages, **kwargs) -> dict:
        return regression_payload(
            flow=self.flow,
            root=self.root,
            tool=TOOL,
            run_dir=self.run_dir,
            jobs=jobs,
            stages=stages,
            args=self.args,
            items=ITEMS,
            elapsed_sec=3.0,
            versions={TOOL: "5.0"},
            git_metadata={},
            **kwargs,
        )


class RunCompletion(unittest.TestCase):
    def test_every_planned_leaf_ran(self):
        self.assertEqual(
            run_completion(3, 3, None),
            {"completed": True, "leaves_planned": 3, "leaves_run": 3},
        )

    def test_without_a_plan_the_executed_leaves_are_the_plan(self):
        self.assertEqual(
            run_completion(2, None, None),
            {"completed": True, "leaves_planned": 2, "leaves_run": 2},
        )

    def test_truncated_plan_is_incomplete(self):
        self.assertEqual(
            run_completion(2, 3, None),
            {"completed": False, "leaves_planned": 3, "leaves_run": 2},
        )

    def test_snapshot_with_progress_is_never_complete(self):
        progress = {**interrupted_progress(3, 3), "state": "running"}
        self.assertEqual(
            run_completion(3, 3, progress),
            {"completed": False, "leaves_planned": 3, "leaves_run": 3},
        )

    def test_progress_plan_wins_over_the_argument(self):
        completion = run_completion(1, None, interrupted_progress(3, 1))
        self.assertEqual(completion["leaves_planned"], 3)
        self.assertFalse(completion["completed"])


class InterruptedResult(FixtureCase):
    def test_interrupted_run_publishes_no_pass_rate(self):
        payload = self.result(
            [leaf("t_alpha")],
            status_override="ERROR",
            progress=interrupted_progress(3, 1),
            interruption=INTERRUPTION,
            planned_leaves=3,
        )
        self.assertEqual(payload["status"], "ERROR")
        tests = payload["tests"]
        self.assertIsNone(tests["pass_rate"])
        self.assertFalse(tests["completed"])
        self.assertEqual(tests["leaves_run"], 1)
        self.assertEqual(tests["leaves_planned"], 3)
        self.assertEqual(tests["passing"], 1)
        self.assertEqual(tests["total"], 1)
        self.assertFalse(run_is_complete(payload))
        self.assertEqual(
            incomplete_run_note(tests),
            "incomplete run: 1 of 3 planned leaves ran, no pass rate",
        )

    def test_interrupted_regression_summary_publishes_no_pass_rate(self):
        payload = self.regression(
            [job("t_alpha"), job("t_beta", "FAIL")],
            [leaf("t_alpha"), leaf("t_beta", "FAIL")],
            status_override="ERROR",
            progress=interrupted_progress(3, 2),
            interruption=INTERRUPTION,
            planned_leaves=3,
        )
        tests = payload["tests"]
        self.assertIsNone(tests["pass_rate"])
        self.assertFalse(tests["completed"])
        self.assertEqual((tests["leaves_run"], tests["leaves_planned"]), (2, 3))
        self.assertEqual((tests["passing"], tests["failing"]), (1, 1))
        self.assertEqual(payload["status"], "ERROR")

    def test_running_checkpoint_publishes_no_pass_rate(self):
        progress = {**interrupted_progress(3, 1), "state": "running", "interrupted_count": 0}
        payload = self.result(
            [leaf("t_alpha")], status_override="UNKNOWN", progress=progress, planned_leaves=3
        )
        self.assertIsNone(payload["tests"]["pass_rate"])
        self.assertFalse(payload["tests"]["completed"])
        self.assertFalse(run_is_complete(payload))

    def test_stopped_early_without_a_signal_is_incomplete(self):
        payload = self.result([leaf("t_alpha"), leaf("t_beta", "FAIL")], planned_leaves=3)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIsNone(payload["tests"]["pass_rate"])
        self.assertFalse(payload["tests"]["completed"])
        self.assertFalse(run_is_complete(payload))

    def test_leaves_skipped_after_max_failures_did_not_run(self):
        skipped = leaf("t_gamma", "SKIP")
        skipped.reason = "skipped after --max-failures threshold"
        payload = self.result(
            [leaf("t_alpha", "FAIL"), leaf("t_beta", "FAIL"), skipped], planned_leaves=3
        )
        tests = payload["tests"]
        self.assertFalse(tests["completed"])
        self.assertIsNone(tests["pass_rate"])
        self.assertEqual(
            (tests["leaves_run"], tests["leaves_planned"], tests["skipped"]), (2, 3, 1)
        )
        self.assertFalse(run_is_complete(payload))

    def test_regression_summary_skipped_after_max_failures_did_not_run(self):
        payload = self.regression(
            [job("t_alpha", "FAIL"), job("t_beta", "FAIL"), job("t_gamma", "SKIP")],
            [leaf("t_alpha", "FAIL"), leaf("t_beta", "FAIL"), leaf("t_gamma", "SKIP")],
            planned_leaves=3,
        )
        tests = payload["tests"]
        self.assertFalse(tests["completed"])
        self.assertIsNone(tests["pass_rate"])
        self.assertEqual((tests["leaves_run"], tests["leaves_planned"]), (2, 3))

    def test_console_summary_counts_skipped_leaves_as_not_run(self):
        stream = io.StringIO()
        console = Console("plain", stream=stream)
        console._fd = None
        console.regression_summary(
            {
                "t_alpha": [(1, leaf("t_alpha", "FAIL"))],
                "t_beta": [(1, leaf("t_beta", "SKIP"))],
            },
            ordered_items=["t_alpha", "t_beta"],
            elapsed_sec=2.0,
            planned=2,
        )
        self.assertIn("skipped=1 elapsed=2.0s incomplete=1/2", stream.getvalue())

    def test_pretty_console_summary_counts_skipped_leaves_as_not_run(self):
        stream = io.StringIO()
        console = Console("pretty", stream=stream)
        console._fd = None
        console.regression_summary(
            {
                "t_alpha": [(1, leaf("t_alpha", "FAIL"))],
                "t_beta": [(1, leaf("t_beta", "SKIP"))],
            },
            ordered_items=["t_alpha", "t_beta"],
            elapsed_sec=2.0,
            planned=2,
        )
        self.assertIn("incomplete run, 1 of 2 planned leaves ran", stream.getvalue())

    def test_interrupt_clears_the_leaf_ui_suppression(self):
        stream = io.StringIO()
        console = Console("plain", stream=stream)
        console._fd = None
        suppression = console.suppress(True)
        suppression.__enter__()
        console.event("result", "muted")
        console.clear_suppression()
        console.event("result", "audible")
        self.assertNotIn("muted", stream.getvalue())
        self.assertIn("audible", stream.getvalue())

    def test_regrade_refuses_an_incomplete_run(self):
        payload = self.result(
            [leaf("t_alpha")],
            status_override="ERROR",
            progress=interrupted_progress(3, 1),
            interruption=INTERRUPTION,
            planned_leaves=3,
        )
        with self.assertRaises(ConfigError) as ctx:
            _require_completed_run(payload, self.run_dir / "result.json")
        self.assertIn("1 of 3 planned leaves ran", str(ctx.exception))
        self.assertIn("not gradeable", str(ctx.exception))

    def test_interruption_junit_names_the_truncation(self):
        xml_path = materialize_interruption_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            interruption=INTERRUPTION,
            progress=interrupted_progress(3, 1),
        )
        self.assertEqual(xml_path, self.run_dir / "results" / "results.xml")
        suites = ET.parse(xml_path).getroot()
        self.assertEqual(suites.get("tests"), "1")
        self.assertEqual(suites.get("errors"), "1")
        error = suites.find("./testsuite/testcase/error")
        self.assertIsNotNone(error)
        self.assertEqual(error.get("type"), "interruption")
        self.assertEqual(
            error.get("message"), "run interrupted by SIGTERM: 1 of 3 planned leaves ran"
        )

    def test_console_reports_an_incomplete_run(self):
        stream = io.StringIO()
        console = Console("plain", stream=stream)
        console._fd = None
        console.result(
            status="ERROR",
            elapsed_sec=3.0,
            tests=3,
            run_dir="dut/build/runs/r",
            result_json="dut/build/runs/r/result.json",
            incomplete="incomplete run: 1 of 3 planned leaves ran, no pass rate",
        )
        self.assertIn("status=ERROR", stream.getvalue())
        self.assertIn("incomplete run: 1 of 3 planned leaves ran", stream.getvalue())


class CompleteResult(FixtureCase):
    def test_complete_run_keeps_its_pass_rate(self):
        payload = self.result(
            [leaf("t_alpha"), leaf("t_beta"), leaf("t_gamma", "FAIL")], planned_leaves=3
        )
        tests = payload["tests"]
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(tests["pass_rate"], 0.6667)
        self.assertTrue(tests["completed"])
        self.assertEqual((tests["leaves_run"], tests["leaves_planned"]), (3, 3))
        self.assertTrue(run_is_complete(payload))
        self.assertIsNone(incomplete_run_note(tests))
        _require_completed_run(payload, self.run_dir / "result.json")

    def test_complete_regression_summary_keeps_its_pass_rate(self):
        payload = self.regression(
            [job(item) for item in ITEMS], [leaf(item) for item in ITEMS], planned_leaves=3
        )
        tests = payload["tests"]
        self.assertEqual(tests["pass_rate"], 1.0)
        self.assertTrue(tests["completed"])
        self.assertEqual(payload["status"], "PASS")

    def test_leaf_errors_in_a_finished_run_still_grade(self):
        payload = self.result(
            [leaf("t_alpha"), leaf("t_beta", "ERROR"), leaf("t_gamma")], planned_leaves=3
        )
        self.assertEqual(payload["status"], "ERROR")
        self.assertEqual(payload["tests"]["pass_rate"], 0.6667)
        self.assertTrue(payload["tests"]["completed"])

    def test_records_without_completion_fields_read_as_complete(self):
        self.assertTrue(run_is_complete({"status": "PASS", "tests": {"pass_rate": 1.0}}))
        self.assertFalse(run_is_complete({"status": "ERROR", "interruption": INTERRUPTION}))


if __name__ == "__main__":
    unittest.main()
