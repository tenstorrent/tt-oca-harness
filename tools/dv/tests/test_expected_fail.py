# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the `expect_fail` testlist key and its leaf grading.

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
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import stages  # noqa: E402
from runlib.config import load_simulators, load_test_catalog  # noqa: E402
from runlib.junit import PRODUCER  # noqa: E402
from runlib.logparse import (  # noqa: E402
    log_failure_messages,
    validate_parser_registry,
    xunit_failure_messages,
)
from runlib.models import ConfigError, Dut, TestCatalog, TestEntry  # noqa: E402
from runlib.results import _is_expected_failure  # noqa: E402
from runlib.stages import grade_expected_fail  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
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

    def test_match_regex_is_kept_on_the_entry(self):
        catalog = load_test_catalog(
            make_dut(
                [
                    {
                        "name": "t1",
                        "run_modes": ["smoke"],
                        "expect_fail": "#1 defect",
                        "expect_fail_match": r"wrap_to_live=[1-9]",
                    }
                ]
            ),
            Path("."),
        )
        self.assertEqual(catalog.tests["t1"].expect_fail_match, r"wrap_to_live=[1-9]")
        self.assertIsNone(
            load_test_catalog(
                make_dut([{"name": "t2", "run_modes": ["smoke"], "expect_fail": "#1"}]), Path(".")
            )
            .tests["t2"]
            .expect_fail_match
        )

    def test_match_without_reason_is_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(
                make_dut([{"name": "t1", "run_modes": ["smoke"], "expect_fail_match": "x"}]),
                Path("."),
            )
        self.assertIn("requires expect_fail", str(ctx.exception))

    def test_invalid_or_blank_match_is_rejected(self):
        for bad in ("(", "  ", True):
            with self.assertRaises(ConfigError, msg=repr(bad)):
                load_test_catalog(
                    make_dut(
                        [
                            {
                                "name": "t1",
                                "run_modes": ["smoke"],
                                "expect_fail": "#1",
                                "expect_fail_match": bad,
                            }
                        ]
                    ),
                    Path("."),
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

    def test_observed_failures_are_recorded_and_a_matching_message_grades_pass(self):
        failures = ["SMC deadspace aliased live registers (wrap_to_live=7 read_alias=6)"]
        status, reason, buckets, record = grade_expected_fail(
            "FAIL",
            "1 testcase failure/error node(s)",
            None,
            self.REASON,
            observed_failures=failures,
            expect_fail_match=r"wrap_to_live=[1-9]",
        )
        self.assertEqual(status, "PASS")
        self.assertEqual(reason, f"expected_fail: {self.REASON}")
        self.assertIsNone(buckets)
        self.assertEqual(record["observed_failures"], failures)
        self.assertEqual(record["observed_buckets"], [])
        self.assertEqual(record["match"], r"wrap_to_live=[1-9]")

    def test_a_different_failure_than_recorded_grades_fail(self):
        status, reason, buckets, record = grade_expected_fail(
            "FAIL",
            "1 testcase failure/error node(s)",
            [{"kind": "test_fail"}],
            self.REASON,
            observed_failures=["TIMEOUT waiting for pready at 0xc0160038"],
            expect_fail_match=r"wrap_to_live=[1-9]",
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("failed for another reason", reason)
        self.assertIn("TIMEOUT waiting for pready", reason)
        self.assertEqual([bucket["kind"] for bucket in buckets], ["expected_fail_mismatch"])
        self.assertEqual(record["observed_status"], "FAIL")
        self.assertEqual(record["observed_buckets"], [{"kind": "test_fail", "signature": None}])

    def test_a_match_with_no_failure_message_grades_fail(self):
        status, reason, buckets, _ = grade_expected_fail(
            "FAIL", "r", None, self.REASON, observed_failures=[], expect_fail_match="x"
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("no failure message recorded", reason)
        self.assertEqual(buckets[0]["kind"], "expected_fail_mismatch")

    def test_without_a_match_any_failure_message_is_the_recorded_one(self):
        status, _, _, record = grade_expected_fail(
            "FAIL", "r", None, self.REASON, observed_failures=["anything"]
        )
        self.assertEqual(status, "PASS")
        self.assertEqual(record["observed_failures"], ["anything"])
        self.assertNotIn("match", record)
        self.assertNotIn("matched_failure", record)

    def test_a_match_past_the_recorded_messages_grades_pass_and_names_it(self):
        failures = [f"UVM_ERROR other [OTHER_{index}]" for index in range(30)]
        failures.append("UVM_ERROR reporter [dtp_scoreboard] CHK-SB-IDCODE FAIL")
        status, _, _, record = grade_expected_fail(
            "FAIL",
            "r",
            None,
            self.REASON,
            observed_failures=failures,
            expect_fail_match=r"CHK-SB-IDCODE FAIL",
        )
        self.assertEqual(status, "PASS")
        self.assertEqual(record["observed_failures"], failures[:8])
        self.assertEqual(record["matched_failure"], failures[-1])

    def test_a_match_past_the_recorded_width_grades_pass(self):
        line = "UVM_ERROR " + "p" * 420 + " tail_ctx=7"
        status, _, _, record = grade_expected_fail(
            "FAIL",
            "r",
            None,
            self.REASON,
            observed_failures=[line],
            expect_fail_match=r"tail_ctx=[1-9]",
        )
        self.assertEqual(status, "PASS")
        self.assertEqual(record["observed_failures"], [line[:400]])
        self.assertEqual(record["matched_failure"], line[:400])

    def test_a_mismatch_names_the_first_message_cut_to_the_recorded_width(self):
        line = "UVM_ERROR " + "p" * 500
        status, reason, _, record = grade_expected_fail(
            "FAIL",
            "r",
            None,
            self.REASON,
            observed_failures=[line],
            expect_fail_match=r"never_seen",
        )
        self.assertEqual(status, "FAIL")
        self.assertTrue(reason.endswith(f"failed for another reason: {line[:400]}"))
        self.assertNotIn("matched_failure", record)

    def test_summary_counts_only_graded_expected_failures(self):
        fail_record = grade_expected_fail("FAIL", "r", None, self.REASON)[3]
        pass_record = grade_expected_fail("PASS", "r", None, self.REASON)[3]
        self.assertTrue(_is_expected_failure({"expected_fail": fail_record}, "PASS"))
        self.assertFalse(_is_expected_failure({"expected_fail": pass_record}, "FAIL"))
        self.assertFalse(_is_expected_failure({}, "PASS"))
        self.assertFalse(_is_expected_failure(None, "PASS"))


class XunitFailureMessages(unittest.TestCase):
    def _write(self, body: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False)
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        tmp.write(body)
        tmp.close()
        return Path(tmp.name)

    def test_cocotb_error_msg_junit_message_and_text_are_all_read(self):
        path = self._write(
            "<testsuites><testsuite><testcase name='a'>"
            "<failure error_type='AssertionError' error_msg='wrap_to_live=7 read_alias=6' />"
            "</testcase><testcase name='b'><failure message='resp=0 (expected SLVERR)' />"
            "</testcase><testcase name='c'><error>Traceback\nsecond line</error>"
            "</testcase><testcase name='d'/></testsuite></testsuites>"
        )
        self.assertEqual(
            xunit_failure_messages(path),
            ["wrap_to_live=7 read_alias=6", "resp=0 (expected SLVERR)", "Traceback"],
        )

    def test_missing_or_malformed_file_yields_no_messages(self):
        self.assertEqual(xunit_failure_messages(Path("/nonexistent/results.xml")), [])
        self.assertEqual(xunit_failure_messages(self._write("<testsuites>")), [])


UVM_POLICY = {
    "strip_ansi": True,
    "fail_patterns": [
        r"^UVM_ERROR\s[^:].*$",
        r"^UVM_FATAL\s[^:].*$",
        "UVM TEST FAILED",
        r"^\s*Error:.*",
    ],
    "ignore_patterns": [r"known_x\.sv"],
}


class LogFailureMessages(unittest.TestCase):
    def messages(self, text: str, policy: dict = UVM_POLICY) -> list[str]:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        tmp.write(text)
        tmp.close()
        return log_failure_messages(Path(tmp.name), policy)

    def test_lines_come_whole_once_each_and_in_log_order(self):
        log = (
            "UVM_INFO @ 0: reporter [RNTST] Running test t_x...\n"
            "UVM_FATAL @ 10: env [CFG] missing config\n"
            "UVM_ERROR @ 20: env.sb [SB] mismatch\n"
            "UVM_ERROR @ 25: uvm_test_top [t_x] UVM TEST FAILED\n"
            "UVM_ERROR :    2\n"
            "UVM_FATAL :    1\n"
            "UVM_INFO @ 30: uvm_test_top [t_x] UVM TEST FAILED; UVM TEST FAILED\n"
        )
        self.assertEqual(
            self.messages(log),
            [
                "UVM_FATAL @ 10: env [CFG] missing config",
                "UVM_ERROR @ 20: env.sb [SB] mismatch",
                "UVM_ERROR @ 25: uvm_test_top [t_x] UVM TEST FAILED",
                "UVM_INFO @ 30: uvm_test_top [t_x] UVM TEST FAILED; UVM TEST FAILED",
            ],
        )

    def test_ansi_escapes_are_stripped_before_matching(self):
        self.assertEqual(
            self.messages("\x1b[31mUVM_ERROR @ 5: sb [SB] red\x1b[0m\n"),
            ["UVM_ERROR @ 5: sb [SB] red"],
        )

    def test_an_ignored_match_is_not_a_message(self):
        log = (
            "Error: known_x.sv(3): waived\n"
            "Error: other.sv(4): real\n"
            "UVM_INFO /w/known_x.sv(9) @ 30: uvm_test_top [t_x] UVM TEST FAILED\n"
        )
        # The ignore patterns test the matched text, so a waived name outside the match
        # keeps the line.
        self.assertEqual(
            self.messages(log),
            [
                "Error: other.sv(4): real",
                "UVM_INFO /w/known_x.sv(9) @ 30: uvm_test_top [t_x] UVM TEST FAILED",
            ],
        )

    def test_a_match_that_opens_on_a_blank_line_reports_its_own_line(self):
        self.assertEqual(self.messages("ok\n\nError: late\n"), ["Error: late"])

    def test_lines_split_where_the_parser_splits_them(self):
        # Reading the log turns a carriage return into a newline; a form feed stays inside
        # the line, so `^` does not match after it.
        self.assertEqual(
            self.messages("progress\rUVM_ERROR @ 1: sb [SB] boom\n"),
            ["UVM_ERROR @ 1: sb [SB] boom"],
        )
        self.assertEqual(self.messages("progress\x0cUVM_ERROR @ 1: sb [SB] boom\n"), [])

    def test_a_policy_without_ansi_stripping_keeps_the_escapes(self):
        policy = {**UVM_POLICY, "strip_ansi": False}
        self.assertEqual(self.messages("\x1b[31mUVM_ERROR @ 5: x\n", policy), [])

    def test_a_missing_log_yields_no_messages(self):
        self.assertEqual(log_failure_messages(Path("/nonexistent/sim.log"), UVM_POLICY), [])


SB_MISMATCH = (
    "UVM_ERROR /w/tb/sb.sv(120) @ 1500: uvm_test_top.env.sb [SB_MISMATCH] "
    "wrap_to_live=7 read_alias=6"
)
SB_OTHER = "UVM_ERROR /w/tb/sb.sv(121) @ 1600: uvm_test_top.env.sb [SB_OTHER] second failure"
UVM_SUMMARY = ["--- UVM Report Summary ---", "UVM_ERROR :    2", "UVM_FATAL :    0"]
UVM_LOG = "\n".join(
    ["UVM_INFO @ 0: reporter [RNTST] Running test t_x...", SB_MISMATCH, SB_OTHER, *UVM_SUMMARY]
)


class ExpectFailRunStage(unittest.TestCase):
    """A whole `sim` leaf through `run_stage`, with a `noop` stage whose note is the log."""

    @classmethod
    def setUpClass(cls):
        cls.policies = validate_parser_registry(REPO_ROOT)
        cls.simulators = load_simulators(REPO_ROOT)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def run_leaf(
        self, match, log=UVM_LOG, framework="uvm", tool="vcs", pass_fail=None, dry_run=False
    ):
        raw = {"native": {"stages": {"sim": {"kind": "noop", "note": log}}}}
        if pass_fail is not None:
            raw["pass_fail"] = pass_fail
        flow = Dut(
            name="fixture",
            kind="sim",
            description="expect_fail fixture",
            framework=framework,
            visibility="public",
            runnability="runnable",
            license="Apache-2.0",
            root="dut",
            default_tool=tool,
            tools=[tool],
            path=self.root / "dut" / "fixture_sim_cfg.toml",
            raw=raw,
            frameworks=[framework],
            default_framework=framework,
        )
        entry = TestEntry(
            name="t_x", module="t_x", expect_fail="#1 defect", expect_fail_match=match
        )
        catalog = TestCatalog(path=None, groups={}, tests={"t_x": entry})
        args = Namespace(
            dry_run=dry_run,
            quiet=True,
            verbose=False,
            timeout=None,
            ui="plain",
            seed=None,
            sim_jobs=1,
            cov=False,
            waves=None,
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return stages.run_stage(
                flow,
                self.root,
                raw,
                catalog,
                "sim",
                "t_x",
                args,
                tool,
                self.root / "run",
                self.simulators,
                self.policies,
            )

    def leaf_xml(self) -> Path:
        return self.root / "run" / "t_x" / "results" / "results.xml"

    def test_a_matching_log_line_grades_pass(self):
        result = self.run_leaf(r"\[SB_MISMATCH\] wrap_to_live=[1-9]")
        self.assertEqual(result.status, "PASS", result.reason)
        self.assertIsNone(result.failure_buckets)
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_failures"], [SB_MISMATCH, SB_OTHER])
        self.assertEqual(record["matched_failure"], SB_MISMATCH)

    def test_without_a_match_the_log_failures_are_still_recorded(self):
        result = self.run_leaf(None)
        self.assertEqual(result.status, "PASS", result.reason)
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_failures"], [SB_MISMATCH, SB_OTHER])
        self.assertNotIn("match", record)
        self.assertNotIn("matched_failure", record)

    def test_a_different_log_failure_names_the_first_line(self):
        result = self.run_leaf(r"never_seen")
        self.assertEqual(result.status, "FAIL")
        self.assertEqual([b["kind"] for b in result.failure_buckets], ["expected_fail_mismatch"])
        self.assertIn(f"failed for another reason: {SB_MISMATCH}", result.reason)

    def test_the_log_is_read_when_the_parser_stops_before_its_fail_patterns(self):
        result = self.run_leaf(r"\[SB_MISMATCH\]", log=f"{SB_MISMATCH}\nsimv killed")
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_reason"], "required pattern missing: UVM Report Summary")
        self.assertEqual(result.status, "PASS", result.reason)

    def test_a_failure_with_no_error_line_has_no_message(self):
        log = "\n".join(["--- UVM Report Summary ---", "UVM_ERROR :    3", "UVM_FATAL :    0"])
        result = self.run_leaf(r"UVM_ERROR", log=log)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("no failure message recorded", result.reason)

    def test_flow_ignore_patterns_and_simulator_fail_patterns_both_apply(self):
        log = "\n".join(["Error: known_x.sv(3): waived", "Error: other.sv(4): real", *UVM_SUMMARY])
        result = self.run_leaf(
            r"never_seen", log=log, pass_fail={"extra_ignore_patterns": [r"known_x\.sv"]}
        )
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_failures"], ["Error: other.sv(4): real"])

    def test_a_rerun_never_reads_the_previous_synthesized_xml(self):
        self.assertEqual(self.run_leaf(r"never_seen").status, "FAIL")
        self.assertTrue(self.leaf_xml().is_file())
        result = self.run_leaf(r"failed for another reason")
        self.assertEqual(result.status, "FAIL", result.reason)
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_failures"], [SB_MISMATCH, SB_OTHER])

    def test_a_rerun_replaces_the_previous_synthesized_xml(self):
        self.assertEqual(self.run_leaf(r"\[SB_MISMATCH\]").status, "PASS")
        result = self.run_leaf(r"never_seen")
        self.assertEqual(result.status, "FAIL")
        failures = list(ET.parse(self.leaf_xml()).getroot().iter("failure"))
        self.assertEqual([node.get("message") for node in failures], [result.reason])

    def test_a_uvm_leaf_never_reads_an_xml_the_framework_did_not_write(self):
        xml = self.leaf_xml()
        xml.parent.mkdir(parents=True)
        body = (
            "<testsuites><testsuite><testcase name='t_x'>"
            "<failure error_msg='stale cocotb failure'/></testcase>"
            "</testsuite></testsuites>"
        )
        xml.write_text(body)
        result = self.run_leaf(r"stale")
        self.assertEqual(result.status, "FAIL", result.reason)
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_failures"], [SB_MISMATCH, SB_OTHER])
        self.assertEqual(xml.read_text(), body)

    def test_a_dry_run_keeps_the_previous_synthesized_xml(self):
        self.assertEqual(self.run_leaf(r"never_seen").status, "FAIL")
        body = self.leaf_xml().read_text()
        self.run_leaf(r"never_seen", dry_run=True)
        self.assertEqual(self.leaf_xml().read_text(), body)

    def test_a_cocotb_leaf_reads_its_own_xml_and_not_its_log(self):
        xml = self.leaf_xml()
        xml.parent.mkdir(parents=True)
        body = (
            "<testsuites><testsuite><testcase name='t_x'>"
            "<failure error_msg='wrap_to_live=7 read_alias=6'/></testcase>"
            "</testsuite></testsuites>"
        )
        xml.write_text(body)
        result = self.run_leaf(
            r"wrap_to_live=[1-9]", log="TEST FAILED", framework="cocotb", tool="verilator"
        )
        self.assertEqual(result.status, "PASS", result.reason)
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_failures"], ["wrap_to_live=7 read_alias=6"])
        self.assertEqual(xml.read_text(), body)

    def test_a_cocotb_match_past_the_recorded_width_or_count_grades_pass(self):
        xml = self.leaf_xml()
        xml.parent.mkdir(parents=True)
        wide = "AssertionError: " + "x" * 420 + " wrap_to_live=7"
        for match, nodes in (
            (r"wrap_to_live=[1-9]", [wide]),
            (
                r"read_alias=[1-9]",
                [f"other failure {index}" for index in range(8)] + ["read_alias=6"],
            ),
        ):
            with self.subTest(match=match):
                cases = "".join(
                    f"<testcase name='c{index}'><failure error_msg='{node}'/></testcase>"
                    for index, node in enumerate(nodes)
                )
                xml.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
                result = self.run_leaf(
                    match, log="TEST FAILED", framework="cocotb", tool="verilator"
                )
                self.assertEqual(result.status, "PASS", result.reason)
                record = result.metadata["expected_fail"]
                self.assertEqual(record["matched_failure"], nodes[-1][:400])
                self.assertEqual(len(record["observed_failures"]), min(len(nodes), 8))

    def test_a_cocotb_file_that_reads_as_a_pass_gets_graded_xml_only_when_the_leaf_fails(self):
        xml = self.leaf_xml()
        graded = xml.with_name("graded.xml")
        body = "<testsuites><testsuite><testcase name='t_x'/></testsuite></testsuites>"
        for log, status in (("TEST FAILED", "PASS"), ("TEST PASSED", "FAIL")):
            with self.subTest(log=log):
                xml.parent.mkdir(parents=True, exist_ok=True)
                xml.write_text(body)
                result = self.run_leaf(None, log=log, framework="cocotb", tool="verilator")
                self.assertEqual(result.status, status, result.reason)
                self.assertEqual(xml.read_text(), body)
                if status == "PASS":
                    self.assertFalse(graded.exists())
                    continue
                failure = ET.parse(graded).getroot().find("./testsuite/testcase/failure")
                assert failure is not None
                self.assertEqual(failure.get("type"), "expected_fail_passed")

    def test_a_cocotb_leaf_never_grades_a_previous_synthesized_xml(self):
        xml = self.leaf_xml()
        xml.parent.mkdir(parents=True)
        xml.write_text(
            "<testsuites><testsuite><properties>"
            f"<property name='producer' value='{PRODUCER}'/></properties>"
            "<testcase name='t_x'><failure message='stale'/></testcase>"
            "</testsuite></testsuites>"
        )
        result = self.run_leaf(r"stale", log="no verdict", framework="cocotb", tool="verilator")
        self.assertEqual(result.status, "UNKNOWN", result.reason)


if __name__ == "__main__":
    unittest.main()
