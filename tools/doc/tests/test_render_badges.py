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
import render_badges  # noqa: E402
from render_badges import AMBER, GREEN, GREY, RED, badges_for, band, measure, percent  # noqa: E402


class PercentTests(unittest.TestCase):
    """The published value is whatever the run wrote, of any type."""

    def test_reads_a_number_and_nothing_else(self):
        for value, expected in ((88, 88.0), (88.4, 88.4)):
            with self.subTest(value=value):
                self.assertEqual(percent(value), expected)

        for value in ("88.4", True, None, [], {}):
            with self.subTest(value=value):
                self.assertIsNone(percent(value))


class MeasureTests(unittest.TestCase):
    def test_rounds_a_measured_value_and_names_an_absent_one(self):
        self.assertEqual(measure(88.44), "88.4 %")
        self.assertEqual(measure(0.0), "0.0 %")
        self.assertEqual(measure(None), "no data")


class BandTests(unittest.TestCase):
    def test_bands_on_the_thresholds(self):
        self.assertEqual(band(render_badges.PASS_AT), GREEN)
        self.assertEqual(band(render_badges.PASS_AT - 0.1), AMBER)
        self.assertEqual(band(render_badges.WARN_AT), AMBER)
        self.assertEqual(band(render_badges.WARN_AT - 0.1), RED)
        # Unmeasured is not a failure.
        self.assertEqual(band(None), GREY)


class BadgesForTests(unittest.TestCase):
    def test_bands_the_status_a_run_reported(self):
        for status, state, colour in (
            ("PASS", "passing", GREEN),
            ("FAIL", "fail", RED),
            ("ERROR", "error", RED),
            ("SKIP", "skip", GREY),
            ("NOTRUN", "notrun", GREY),
            ("", "no data", GREY),
        ):
            with self.subTest(status=status):
                badges = badges_for({"flow": "dtp", "status": status}, None)
                self.assertEqual(badges["status"], ("dtp", state, colour))

    def test_reports_a_measured_rate_and_coverage(self):
        badges = badges_for(
            {"flow": "dtp", "status": "PASS", "pass_rate": 100.0}, {"total_percent": 79.83}
        )
        self.assertEqual(sorted(badges), ["coverage", "status", "tests"])
        self.assertEqual(badges["tests"], ("tests", "100.0 %", GREEN))
        self.assertEqual(badges["coverage"], ("coverage", "79.8 %", AMBER))

    def test_anything_unusable_reads_as_no_data_rather_than_raising(self):
        for dut, coverage in (
            ({"flow": "dtp"}, None),
            ({"flow": "dtp"}, {"total_percent": None}),
            ({"flow": "dtp"}, ["not", "a", "dict"]),
            ({"flow": "dtp", "pass_rate": "100.0"}, "not a dict"),
        ):
            with self.subTest(coverage=coverage):
                badges = badges_for(dut, coverage)
                self.assertEqual(badges["tests"][1], "no data")
                self.assertEqual(badges["coverage"], ("coverage", "no data", GREY))

    def test_every_label_names_the_series_it_reports(self):
        for dut, labels in (
            (
                {"flow": "dtp", "framework": "uvm", "tool": "vcs"},
                ("dtp (uvm, vcs)", "tests (uvm, vcs)", "coverage (uvm, vcs)"),
            ),
            ({"flow": "dtp"}, ("dtp", "tests", "coverage")),
        ):
            with self.subTest(dut=dut):
                badges = badges_for({"status": "PASS", **dut}, None)
                self.assertEqual(
                    tuple(badges[kind][0] for kind in ("status", "tests", "coverage")), labels
                )

    def test_only_a_run_that_completed_no_tests_loses_its_verdict(self):
        for total, state in ((0, "no data"), (False, "fail"), (151, "fail"), (None, "fail")):
            with self.subTest(tests_total=total):
                dut = {"flow": "sep", "status": "FAIL", "tests_total": total}
                self.assertEqual(badges_for(dut, None)["status"][1], state)


class NamePartTests(unittest.TestCase):
    """Each part of a series names a file, so it is restricted, not escaped."""

    def test_accepts_a_published_name_and_rejects_a_path(self):
        for part, accepted in (
            ("dtp", True),
            ("chip_ocah", True),
            ("cross_trigger_port", True),
            ("vcs", True),
            ("uvm", True),
            ("../../pwn", False),
            ("a/b", False),
            ("dtp-1", False),
            ("dtp.svg", False),
            ("", False),
        ):
            with self.subTest(part=part):
                self.assertEqual(bool(render_badges.NAME_PART.match(part)), accepted)


class IdentityTests(unittest.TestCase):
    """The three fields naming a series, however incomplete the entry."""

    def test_reads_the_three_fields_and_empties_the_absent(self):
        for entry, expected in (
            ({"flow": "dtp", "framework": "uvm", "tool": "vcs"}, ("dtp", "uvm", "vcs")),
            ({"flow": "dtp"}, ("dtp", "", "")),
            ({}, ("", "", "")),
        ):
            with self.subTest(entry=entry):
                self.assertEqual(render_badges.identity(entry), expected)


class FetchTests(unittest.TestCase):
    """shields.io reads the path, so what goes into it decides the badge."""

    def request_for(self, label, message, colour="#f6c343"):
        """Call fetch() with the network replaced, returning the request it built."""
        opened = mock.MagicMock()
        opened.__enter__.return_value.read.return_value = b"<svg/>"
        with mock.patch.object(render_badges.urllib.request, "urlopen", return_value=opened) as u:
            render_badges.fetch(label, message, colour)
        return u.call_args.args[0]

    def test_builds_the_badge_request(self):
        self.assertIn("100.0%20%25-f6c343", self.request_for("tests", "100.0 %").full_url)
        # A bare "-" would end the message early and "_" would render as a space.
        self.assertIn("not--run", self.request_for("status", "not-run").full_url)
        self.assertIn("did__not__run", self.request_for("status", "did_not_run").full_url)
        # The label is a query parameter, so an underscore survives untouched.
        self.assertIn("label=chip_ocah", self.request_for("chip_ocah", "passing").full_url)
        # shields.io rejects the default urllib agent with 403.
        self.assertEqual(
            self.request_for("tests", "passing").get_header("User-agent"),
            render_badges.USER_AGENT,
        )

    def test_a_refused_fetch_is_not_an_error(self):
        with mock.patch.object(
            render_badges.urllib.request,
            "urlopen",
            side_effect=render_badges.urllib.error.URLError("refused"),
        ):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertIsNone(render_badges.fetch("tests", "passing", GREEN))
        self.assertIn("cannot fetch", err.getvalue())


class MainTests(unittest.TestCase):
    """The published summary in, the staged badges out."""

    SUMMARY = {
        "dut_status": [
            {
                "flow": "dtp",
                "framework": "uvm",
                "tool": "vcs",
                "status": "PASS",
                "tests_total": 151,
                "pass_rate": 100.0,
            },
            {"flow": "../../pwn", "framework": "uvm", "tool": "vcs", "status": "PASS"},
        ],
        "results": [
            {
                "flow": "dtp",
                "framework": "uvm",
                "tool": "vcs",
                "coverage": {"total_percent": 80.0},
            }
        ],
    }

    def run_main(self, outdir, source_text=None, fetched=b"<svg/>"):
        """Run main() against a written summary, returning (code, stdout, stderr)."""
        source = outdir / "summary.json"
        source.write_text(json.dumps(self.SUMMARY) if source_text is None else source_text)

        out, err = io.StringIO(), io.StringIO()
        argv = ["render_badges.py", str(source), str(outdir)]
        self.enterContext(mock.patch.object(sys, "argv", argv))
        # Stand in for the one function that reaches shields.io.
        self.enterContext(mock.patch.object(render_badges, "fetch", return_value=fetched))
        self.enterContext(contextlib.redirect_stdout(out))
        self.enterContext(contextlib.redirect_stderr(err))

        return render_badges.main(), out.getvalue(), err.getvalue()

    def test_writes_one_badge_per_kind_and_skips_an_unsafe_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code, _, err = self.run_main(out)
            self.assertEqual(code, 0)
            self.assertEqual(
                sorted(p.name for p in out.glob("badge-*.svg")),
                [
                    "badge-dtp-uvm-vcs-coverage.svg",
                    "badge-dtp-uvm-vcs-status.svg",
                    "badge-dtp-uvm-vcs-tests.svg",
                ],
            )
            self.assertIn("../../pwn", err)

    def test_removes_a_badge_the_summary_no_longer_has(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            stale = out / "badge-sep-cocotb-vcs-status.svg"
            stale.write_bytes(b"old")
            _, stdout, _ = self.run_main(out)
            self.assertFalse(stale.exists())
            self.assertIn("removed 1 stale", stdout)

    def test_a_failed_fetch_keeps_the_previous_copy_and_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            previous = out / "badge-dtp-uvm-vcs-status.svg"
            previous.write_bytes(b"previous")
            _, _, err = self.run_main(out, fetched=None)
            self.assertEqual(previous.read_bytes(), b"previous")
            self.assertIn("3 of 3 badges unavailable", err)

    def test_reports_a_summary_it_cannot_use(self):
        for text, reason in (
            ("{not json", "cannot read"),
            ("[]", "not a JSON object"),
            ("null", "not a JSON object"),
        ):
            with self.subTest(text=text):
                with tempfile.TemporaryDirectory() as tmp:
                    code, _, err = self.run_main(Path(tmp), source_text=text)
                    self.assertEqual(code, 1)
                    self.assertIn(reason, err)

    def test_survives_a_summary_whose_lists_hold_the_wrong_types(self):
        summary = json.dumps(
            {
                "dut_status": ["a", None, {"flow": "dtp", "framework": "uvm", "tool": "vcs"}],
                "results": {"not": "a list"},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code, _, _ = self.run_main(out, source_text=summary)
            self.assertEqual(code, 0)
            self.assertTrue((out / "badge-dtp-uvm-vcs-status.svg").exists())


if __name__ == "__main__":
    unittest.main()
