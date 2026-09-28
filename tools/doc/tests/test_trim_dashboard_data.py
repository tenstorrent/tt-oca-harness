# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Add the tools under test to the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trim_dashboard_data  # noqa: E402
from trim_dashboard_data import trim_history_point, trim_result, trim_test  # noqa: E402


class TrimTestTests(unittest.TestCase):
    def test_keeps_the_columns_a_block_page_shows(self):
        test = {
            "name": "a",
            "status": "PASS",
            "category": "smoke",
            "seed": 1,
            "duration_sec": 2.5,
            "stage": "run",
            "log": "build/ci/runs/dtp/a.log",
        }
        self.assertEqual(sorted(trim_test(test)), sorted(trim_dashboard_data.TEST_KEYS))
        # An absent field is left out rather than filled in.
        self.assertEqual(trim_test({"name": "a"}), {"name": "a"})


class TrimResultTests(unittest.TestCase):
    def test_keeps_the_flow_and_its_coverage_metrics(self):
        result = {
            "flow": "dtp",
            "status": "FAIL",
            "coverage": {"effective_metrics": {"line": 71.2}, "total_percent": None},
        }
        self.assertEqual(
            trim_result(result),
            {"flow": "dtp", "coverage": {"effective_metrics": {"line": 71.2}}},
        )
        self.assertEqual(trim_result({"flow": "dtp"}), {"flow": "dtp"})


class TrimHistoryPointTests(unittest.TestCase):
    def test_keeps_the_fields_the_trends_page_plots(self):
        point = {
            "generated_at": "2026-08-01T00:00:00+00:00",
            "test_pass_rate": 99.0,
            "flow_pass_rate": 50.0,
            "failed_tests": 1,
            "flaky_tests": 2,
            "junit_xml": "dropped",
            "per_dut": [{"flow": "dtp", "coverage_status": "SKIP", "run_dir": "dropped"}],
        }
        trimmed = trim_history_point(point)
        self.assertNotIn("junit_xml", trimmed)
        self.assertEqual(trimmed["per_dut"], [{"flow": "dtp", "coverage_status": "SKIP"}])
        # per_dut that is not a list of objects is left out rather than raising.
        self.assertEqual(trim_history_point({"failed_tests": 0}), {"failed_tests": 0})
        self.assertEqual(trim_history_point({"per_dut": {"a": 1}}), {})
        self.assertEqual(trim_history_point({"per_dut": ["a", None]})["per_dut"], [])


class SummarySubcommandTests(unittest.TestCase):
    """The page reads these files, so their shape is the contract."""

    SUMMARY = {
        "generated_at": "2026-08-01T00:00:00+00:00",
        "schema_version": "0.1",
        "dut_status": [
            {
                "flow": "dtp",
                "framework": "uvm",
                "tool": "vcs",
                "tests_total": 151,
                "pass_rate": 100.0,
                "coverage_total_percent": 81.7,
                "status": "PASS",
            }
        ],
        "results": [
            {
                "flow": "dtp",
                "framework": "uvm",
                "tool": "vcs",
                "coverage": {"effective_metrics": {"line": 71.2}},
                "tests_detail": [{"name": "a", "status": "PASS", "log": "dropped"}],
            }
        ],
    }

    def run_trim(self, *argv, source_text=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "in.json"
            source.write_text(json.dumps(self.SUMMARY) if source_text is None else source_text)
            paths = [str(source)] + [str(tmp / name) for name in argv]
            full = ["trim_dashboard_data.py", "summary", paths[0], paths[1]]
            if len(paths) > 2:
                full += ["--tests-out", paths[2]]
            err = io.StringIO()
            with mock.patch.object(sys, "argv", full):
                with contextlib.redirect_stderr(err):
                    code = trim_dashboard_data.main()
            written = [
                json.loads(Path(p).read_text()) if Path(p).exists() else None for p in paths[1:]
            ]
            return code, written, err.getvalue()

    def test_drops_every_field_the_pages_do_not_read(self):
        _, (summary, tests), _ = self.run_trim("out.json", "tests.json")
        self.assertNotIn("schema_version", summary)
        self.assertEqual(
            summary["dut_status"],
            [
                {
                    "flow": "dtp",
                    "framework": "uvm",
                    "tool": "vcs",
                    "tests_total": 151,
                    "pass_rate": 100.0,
                    "coverage_total_percent": 81.7,
                }
            ],
        )
        self.assertEqual(
            summary["results"],
            [
                {
                    "flow": "dtp",
                    "framework": "uvm",
                    "tool": "vcs",
                    "coverage": {"effective_metrics": {"line": 71.2}},
                }
            ],
        )
        self.assertEqual(
            tests["results"],
            [
                {
                    "flow": "dtp",
                    "framework": "uvm",
                    "tool": "vcs",
                    "tests": [{"name": "a", "status": "PASS"}],
                }
            ],
        )

    def test_reports_a_source_it_cannot_use(self):
        for text, reason in (("[]", "not a JSON object"), ("{not json", "cannot read")):
            with self.subTest(text=text):
                code, _, err = self.run_trim("out.json", source_text=text)
                self.assertEqual(code, 1)
                self.assertIn(reason, err)

    def test_survives_lists_that_hold_the_wrong_types(self):
        summary = json.dumps({"dut_status": ["a", None, {"flow": "dtp"}], "results": "not a list"})
        code, (trimmed,), _ = self.run_trim("out.json", source_text=summary)
        self.assertEqual(code, 0)
        self.assertEqual(trimmed["dut_status"], [{"flow": "dtp"}])

    def test_a_series_without_detail_is_left_out_of_the_tests_file(self):
        summary = json.dumps({"results": [{"flow": "dtp"}, {"tests_detail": []}]})
        _code, (_summary, tests), _err = self.run_trim(
            "out.json", "tests.json", source_text=summary
        )
        self.assertEqual(tests["results"], [])

    def test_two_frameworks_of_one_block_each_keep_their_tests(self):
        summary = json.dumps(
            {
                "results": [
                    {
                        "flow": "dtp",
                        "framework": "cocotb",
                        "tool": "vcs",
                        "tests_detail": [{"name": "a"}],
                    },
                    {
                        "flow": "dtp",
                        "framework": "uvm",
                        "tool": "vcs",
                        "tests_detail": [{"name": "b"}],
                    },
                ]
            }
        )
        _code, (_summary, tests), _err = self.run_trim(
            "out.json", "tests.json", source_text=summary
        )

        tests_by_framework = {
            series["framework"]: [test["name"] for test in series["tests"]]
            for series in tests["results"]
        }
        self.assertEqual(tests_by_framework, {"cocotb": ["a"], "uvm": ["b"]})


class HistorySubcommandTests(unittest.TestCase):
    def run_trim(self, source_text, out_name="out.json"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source, out = tmp / "in.json", tmp / out_name
            source.write_text(source_text)
            argv = ["trim_dashboard_data.py", "history", str(source), str(out)]
            err = io.StringIO()
            with mock.patch.object(sys, "argv", argv):
                with contextlib.redirect_stderr(err):
                    code = trim_dashboard_data.main()
            written = json.loads(out.read_text()) if out.exists() else None
            return code, written, err.getvalue()

    def test_keeps_only_the_plotted_fields_of_each_point(self):
        source = json.dumps({"points": [{"failed_tests": 1, "junit_xml": "dropped"}], "extra": 1})
        self.assertEqual(self.run_trim(source)[1], {"points": [{"failed_tests": 1}]})

    def test_anything_unplottable_writes_an_empty_series(self):
        for text in ("[]", json.dumps({"points": ["a", None]}), json.dumps({})):
            with self.subTest(text=text):
                self.assertEqual(self.run_trim(text)[1], {"points": []})

    def test_reports_an_unreadable_history(self):
        code, written, err = self.run_trim("{not json")
        self.assertEqual(code, 1)
        self.assertIsNone(written)
        self.assertIn("cannot read", err)

    def test_writes_into_a_directory_that_does_not_exist_yet(self):
        code, written, _ = self.run_trim(json.dumps({"points": []}), out_name="missing/out.json")
        self.assertEqual(code, 0)
        self.assertEqual(written, {"points": []})


class MomentTests(unittest.TestCase):
    """Publishers need not agree on an offset, so stamps compare as moments."""

    def test_an_offset_is_honoured_rather_than_compared_as_text(self):
        # 01:00-05:00 is 06:00Z, later than 02:00Z, though it sorts earlier.
        moment = trim_dashboard_data.moment
        self.assertLess(moment("2026-09-22T02:00:00+00:00"), moment("2026-09-22T01:00:00-05:00"))
        # A stamp carrying no offset is read as UTC.
        self.assertEqual(moment("2026-09-22T02:00:00"), moment("2026-09-22T02:00:00+00:00"))

    def test_anything_unreadable_loses_to_a_usable_stamp(self):
        for raw in (None, "", "not a date", 5, {}):
            with self.subTest(raw=raw):
                self.assertLess(
                    trim_dashboard_data.moment(raw),
                    trim_dashboard_data.moment("2026-09-22T00:00:00+00:00"),
                )


class CombineSubcommandTests(unittest.TestCase):
    """One file per publisher in, the one file the pipeline reads out."""

    def run_combine(self, *documents):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sources = []
            for index, document in enumerate(documents):
                source = tmp / f"{index}.json"
                source.write_text(document if isinstance(document, str) else json.dumps(document))
                sources.append(str(source))
            out = tmp / "out.json"
            argv = ["trim_dashboard_data.py", "combine", str(out)] + sources
            err = io.StringIO()
            with mock.patch.object(sys, "argv", argv):
                with contextlib.redirect_stderr(err):
                    code = trim_dashboard_data.main()
            written = json.loads(out.read_text()) if out.exists() else None
            return code, written, err.getvalue()

    def test_every_publisher_keeps_its_own_entries(self):
        code, written, _ = self.run_combine(
            {"dut_status": [{"flow": "dtp", "framework": "cocotb"}]},
            {"dut_status": [{"flow": "dtp", "framework": "uvm"}]},
        )
        self.assertEqual(code, 0)
        self.assertEqual([entry["framework"] for entry in written["dut_status"]], ["cocotb", "uvm"])

    def test_the_file_is_as_recent_as_its_most_recent_publisher(self):
        _, written, _ = self.run_combine(
            {"generated_at": "2026-09-22T02:00:00+00:00"},
            {"generated_at": "2026-09-22T01:00:00-05:00"},
        )
        self.assertEqual(written["generated_at"], "2026-09-22T01:00:00-05:00")

    def test_points_are_ordered_however_they_arrived(self):
        _, written, _ = self.run_combine(
            {"points": [{"generated_at": "2026-09-22T03:00:00+00:00"}]},
            {"points": [{"generated_at": "2026-09-22T01:00:00+00:00"}]},
        )
        self.assertEqual(
            [point["generated_at"] for point in written["points"]],
            ["2026-09-22T01:00:00+00:00", "2026-09-22T03:00:00+00:00"],
        )

    def test_reports_a_source_it_cannot_use(self):
        for text, reason in (("[]", "not a JSON object"), ("{not json", "cannot read")):
            with self.subTest(text=text):
                code, _, err = self.run_combine({"points": []}, text)
                self.assertEqual(code, 1)
                self.assertIn(reason, err)


if __name__ == "__main__":
    unittest.main()
