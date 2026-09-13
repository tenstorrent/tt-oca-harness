# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Tests for coverage-policy expiry: a lapsed waiver grades as open for its own DUT.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_coverage_closure as closure  # noqa: E402
from runlib.cli import coverage_policy_paths, coverage_policy_warnings  # noqa: E402
from runlib.coverage_policy import (  # noqa: E402
    expired_holes,
    lapsed_warning,
    load_coverage_policy,
)

WAIVER_ID = "toggle-capture_en-rise"
PAST = "2020-01-01"
FUTURE = "2999-12-31"
LAPSED_LINE = f"{WAIVER_ID} expired on {PAST}; treated as open"


def set_expiry(root: Path, value: str) -> Path:
    """Give the fixture's accepted waiver (the first `[[holes]]` entry) an `expires` date."""
    policy = root / closure.POLICY_REL
    text = policy.read_text(encoding="utf-8")
    anchor = 'date = "2026-09-01"\n'
    assert anchor in text
    policy.write_text(text.replace(anchor, anchor + f'expires = "{value}"\n', 1), encoding="utf-8")
    return policy


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = closure.stage_fixture(self.root)

    def graded(self) -> tuple[dict, dict, dict]:
        """Grade the staged run; return summary, details, and policy application."""
        closure.grade_run(self.root, self.run_dir)
        report = self.run_dir / "cov" / "report"
        return (
            read_json(report / "summary.json"),
            read_json(report / "coverage-details.json"),
            read_json(report / "policy-application.json"),
        )

    def pristine_grade(self) -> dict[str, dict]:
        """Grade an untouched copy of the run; return its graded JSON files by name."""
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        closure.grade_run(root, closure.stage_fixture(root))
        return {
            name: read_json(root / rel)
            for name, rel in closure.GRADED_FILES.items()
            if name.endswith(".json")
        }


class PolicyLoading(FixtureCase):
    def test_expired_waiver_loads_as_lapsed(self):
        policy = load_coverage_policy(set_expiry(self.root, PAST), expected_dut=closure.DUT)
        self.assertEqual([rule.expired for rule in policy.holes], [True, False])
        self.assertEqual([rule.id for rule in expired_holes(policy)], [WAIVER_ID])
        self.assertEqual(lapsed_warning(policy.holes[0]), LAPSED_LINE)

    def test_future_expiry_is_not_lapsed(self):
        policy = load_coverage_policy(set_expiry(self.root, FUTURE), expected_dut=closure.DUT)
        self.assertEqual(expired_holes(policy), [])

    def test_validation_reports_the_expiry_as_a_warning(self):
        flow = closure.make_flow(self.root)
        sim_cfg = {"coverage": {closure.TOOL: closure.tool_coverage_cfg()}}
        self.assertEqual(
            coverage_policy_paths(flow, self.root, sim_cfg), [self.root / closure.POLICY_REL]
        )
        self.assertEqual(coverage_policy_warnings(flow, self.root, sim_cfg), [])
        set_expiry(self.root, PAST)
        self.assertEqual(
            coverage_policy_warnings(flow, self.root, sim_cfg),
            [f"{closure.POLICY_REL.as_posix()}: {LAPSED_LINE}"],
        )


class LapsedGrade(FixtureCase):
    def test_lapsed_waiver_grades_as_open_with_a_warning(self):
        set_expiry(self.root, PAST)
        summary, details, application = self.graded()
        holes = summary["holes_summary"]
        self.assertEqual((holes["accepted"], holes["open"], holes["unclassified"]), (0, 6, 4))
        self.assertEqual(summary["metrics"]["toggle"], 50.0)
        waived = [o for o in details["observations"] if o["policy_id"] == WAIVER_ID]
        self.assertEqual(len(waived), 1)
        self.assertEqual((waived[0]["status"], waived[0]["disposition"]), ("open", "waive"))
        self.assertEqual(details["warnings"][-1], LAPSED_LINE)
        self.assertEqual(application["warnings"], [LAPSED_LINE])
        pristine = self.pristine_grade()
        for name, rel in closure.GRADED_FILES.items():
            if name.endswith(".json"):
                with self.subTest(file=name):
                    self.assertEqual(set(read_json(self.root / rel)), set(pristine[name]))

    def test_extending_the_date_restores_the_waiver(self):
        set_expiry(self.root, FUTURE)
        summary, details, application = self.graded()
        holes = summary["holes_summary"]
        self.assertEqual((holes["accepted"], holes["open"]), (1, 5))
        self.assertEqual(summary["metrics"]["toggle"], 60.0)
        pristine = self.pristine_grade()["coverage-details.json"]
        self.assertEqual(details["warnings"], pristine["warnings"])
        self.assertEqual(application["warnings"], [])
        waived = [o for o in details["observations"] if o["policy_id"] == WAIVER_ID]
        self.assertEqual(waived[0]["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
