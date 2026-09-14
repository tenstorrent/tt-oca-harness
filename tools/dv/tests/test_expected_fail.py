# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the `expect_fail` testlist key and its leaf grading.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.config import load_test_catalog  # noqa: E402
from runlib.models import ConfigError, Dut  # noqa: E402
from runlib.results import _is_expected_failure  # noqa: E402
from runlib.stages import grade_expected_fail  # noqa: E402

SMOKE = {"smoke": {"timeout_sec": 60, "args": []}}


def make_dut(tests: list) -> Dut:
    return Dut(
        name="unit",
        kind="sim",
        description="unit-test DUT",
        framework="cocotb",
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root=".",
        default_tool="verilator",
        tools=["verilator"],
        path=Path("test_sim_cfg.toml"),
        raw={"run_modes": SMOKE, "tests": tests},
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


class ExpectFailSchema(unittest.TestCase):
    def test_reason_string_is_kept_on_the_entry(self):
        catalog = load_test_catalog(
            make_dut([{"name": "t1", "run_modes": ["smoke"], "expect_fail": "#1 defect"}]),
            Path("."),
        )
        self.assertEqual(catalog.tests["t1"].expect_fail, "#1 defect")

    def test_absent_key_means_no_expectation(self):
        catalog = load_test_catalog(make_dut([{"name": "t1", "run_modes": ["smoke"]}]), Path("."))
        self.assertIsNone(catalog.tests["t1"].expect_fail)

    def test_bare_flag_is_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(
                make_dut([{"name": "t1", "run_modes": ["smoke"], "expect_fail": True}]), Path(".")
            )
        self.assertIn("t1.expect_fail", str(ctx.exception))

    def test_blank_reason_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_test_catalog(
                make_dut([{"name": "t1", "run_modes": ["smoke"], "expect_fail": "  "}]), Path(".")
            )


class ExpectFailGrading(unittest.TestCase):
    REASON = "#585: dead offsets wrap onto live registers"

    def test_observed_fail_grades_pass_and_records_the_observation(self):
        status, reason, buckets, record = grade_expected_fail(
            "FAIL", "1 testcase failure/error node(s)", [{"kind": "test_fail"}], self.REASON
        )
        self.assertEqual(status, "PASS")
        self.assertEqual(reason, f"expected_fail: {self.REASON}")
        self.assertIsNone(buckets)
        self.assertEqual(record["observed_status"], "FAIL")
        self.assertEqual(record["observed_reason"], "1 testcase failure/error node(s)")
        self.assertEqual(record["reason"], self.REASON)

    def test_observed_pass_grades_fail_in_its_own_bucket(self):
        status, reason, buckets, record = grade_expected_fail(
            "PASS", "positive pass evidence matched", None, self.REASON
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("the defect is gone", reason)
        self.assertIn(self.REASON, reason)
        self.assertEqual([bucket["kind"] for bucket in buckets], ["expected_fail_passed"])
        self.assertEqual(record["observed_status"], "PASS")

    def test_timeout_error_unknown_are_not_the_recorded_failure(self):
        for status in ("TIMEOUT", "ERROR", "UNKNOWN"):
            bucket = [{"kind": status.lower()}]
            graded = grade_expected_fail(status, f"{status} reason", bucket, self.REASON)
            self.assertEqual(graded[0], status, status)
            self.assertEqual(graded[1], f"{status} reason", status)
            self.assertIs(graded[2], bucket, status)
            self.assertEqual(graded[3]["observed_status"], status)

    def test_summary_counts_only_graded_expected_failures(self):
        fail_record = grade_expected_fail("FAIL", "r", None, self.REASON)[3]
        pass_record = grade_expected_fail("PASS", "r", None, self.REASON)[3]
        self.assertTrue(_is_expected_failure({"expected_fail": fail_record}, "PASS"))
        self.assertFalse(_is_expected_failure({"expected_fail": pass_record}, "FAIL"))
        self.assertFalse(_is_expected_failure({}, "PASS"))
        self.assertFalse(_is_expected_failure(None, "PASS"))


if __name__ == "__main__":
    unittest.main()
