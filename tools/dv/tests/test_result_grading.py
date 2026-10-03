# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the rules that grade a simulation leaf and roll leaves up.

The checked-in parser policies grade fixture logs and XML through every status
path; the aggregate order, the exit codes, the flaky and failed regression
records, and the native-versus-synthesized JUnit ownership are checked against
the same fixtures.

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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import junit, stages  # noqa: E402
from runlib.config import load_simulators  # noqa: E402
from runlib.junit import (  # noqa: E402
    PRODUCER,
    REPORT_TAIL_BYTES,
    REPORT_TAIL_LINES,
    ensure_graded_junit,
    ensure_leaf_junit,
    is_generated_junit,
    materialize_interruption_junit,
    materialize_stage_junit,
    report_case_names,
    write_report_junit,
)
from runlib.logparse import parse_stage_result, validate_parser_registry  # noqa: E402
from runlib.models import Dut, StageResult, TestCatalog, TestEntry  # noqa: E402
from runlib.results import (  # noqa: E402
    EXIT_CODE_BY_STATUS,
    aggregate_status,
    exit_code_for_status,
    regression_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = "verilator"

PASSING_XML = (
    '<?xml version="1.0"?><testsuites><testsuite name="s" tests="1">'
    '<testcase classname="t" name="test_a" time="0.1"/></testsuite></testsuites>\n'
)
FAILING_XML = (
    '<?xml version="1.0"?><testsuites><testsuite name="s" tests="1">'
    '<testcase classname="t" name="test_a" time="0.1"><failure message="boom"/></testcase>'
    "</testsuite></testsuites>\n"
)
ERRORED_XML = FAILING_XML.replace("failure", "error")
EMPTY_SUITE_XML = '<?xml version="1.0"?><testsuites><testsuite name="s" tests="0"/></testsuites>\n'
COCOTB_SUMMARY_PASS = "TESTS=2 PASS=2 FAIL=0 SKIP=0\n"
COCOTB_SUMMARY_FAIL = "TESTS=2 PASS=1 FAIL=1 SKIP=0\n"


def make_flow(root: Path, framework: str = "cocotb", raw: dict | None = None) -> Dut:
    return Dut(
        name="fixture",
        kind="sim",
        description="grading fixture",
        framework=framework,
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root="dut",
        default_tool=TOOL,
        tools=[TOOL],
        path=root / "dut" / "fixture_sim_cfg.toml",
        raw=raw or {},
        frameworks=[framework],
        default_framework=framework,
    )


def stage(item: str, status: str, **extra) -> StageResult:
    return StageResult(
        stage=extra.pop("stage", "sim"),
        item=item,
        status=status,
        return_code=EXIT_CODE_BY_STATUS.get(status, 0),
        duration_sec=0.5,
        started_at="2026-09-01T00:00:00+00:00",
        ended_at="2026-09-01T00:00:01+00:00",
        **extra,
    )


class LeafGrading(unittest.TestCase):
    """Every status path of `parse_stage_result` under the checked-in policies."""

    @classmethod
    def setUpClass(cls):
        cls.policies = validate_parser_registry(REPO_ROOT)
        cls.simulators = load_simulators(REPO_ROOT)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.leaf = self.root / "dut" / "build" / "runs" / "r" / "t_a"
        (self.leaf / "results").mkdir(parents=True)
        (self.leaf / "logs").mkdir()

    def grade(self, *, log: str, xml: str | None, rc: int = 0, framework: str = "cocotb"):
        log_path = self.leaf / "logs" / "sim.log"
        log_path.write_text(log, encoding="utf-8")
        xml_path = self.leaf / "results" / "results.xml"
        if xml is not None:
            xml_path.write_text(xml, encoding="utf-8")
        return parse_stage_result(
            flow=make_flow(self.root, framework),
            tool=TOOL,
            policies=self.policies,
            simulators=self.simulators,
            root=self.root,
            log_path=log_path,
            results_dir=self.leaf / "results",
            return_code=rc,
        )

    def test_passing_xml_grades_pass_from_the_structured_result(self):
        decision = self.grade(log="TEST PASSED\n", xml=PASSING_XML)
        self.assertEqual(decision.status, "PASS")
        self.assertEqual(decision.parser["status_source"], "structured_result")
        self.assertEqual(decision.failure_buckets, [])

    def test_failure_node_grades_fail_before_anything_else(self):
        decision = self.grade(log="TEST PASSED\n" + COCOTB_SUMMARY_PASS, xml=FAILING_XML)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.parser["status_source"], "structured_result")
        self.assertEqual(decision.failure_buckets[0]["kind"], "sim_failure")

    def test_missing_xml_with_no_summary_is_unknown(self):
        decision = self.grade(log="TEST PASSED\n", xml=None)
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertIn("structured result missing", decision.reason)
        self.assertEqual(decision.failure_buckets[0]["kind"], "unknown")

    def test_a_graded_xml_beside_the_framework_file_is_never_evidence(self):
        marked = FAILING_XML.replace(
            '<testsuite name="s" tests="1">',
            '<testsuite name="s" tests="1"><properties>'
            f'<property name="producer" value="{PRODUCER}"/></properties>',
        )
        (self.leaf / "results" / "graded.xml").write_text(marked, encoding="utf-8")
        decision = self.grade(log="TEST PASSED\n", xml=PASSING_XML)
        self.assertEqual(decision.status, "PASS", decision.reason)

    def test_empty_malformed_and_caseless_xml_are_unknown(self):
        for body in ("", "<testsuites><testsuite", EMPTY_SUITE_XML):
            with self.subTest(body=body[:20]):
                decision = self.grade(log="", xml=body)
                self.assertEqual(decision.status, "UNKNOWN")
                self.assertEqual(decision.parser["status_source"], "structured_result")

    def test_pass_pattern_alone_is_not_positive_evidence_under_a_structured_policy(self):
        decision = self.grade(log="TEST PASSED\nTEST PASSED\n", xml=None)
        self.assertEqual(decision.status, "UNKNOWN")

    def test_summary_does_not_outrank_a_missing_structured_result(self):
        # The XML stays inconclusive; the remembered gap outranks the summary.
        decision = self.grade(log=COCOTB_SUMMARY_PASS, xml=None)
        self.assertEqual(decision.status, "UNKNOWN")

    def test_hard_fail_pattern_is_error_even_with_passing_xml(self):
        log = "Traceback (most recent call last):\n  boom\n"
        decision = self.grade(log=log, xml=PASSING_XML)
        self.assertEqual(decision.status, "ERROR")
        self.assertEqual(decision.parser["status_source"], "log_pattern")
        self.assertEqual(decision.failure_buckets[0]["kind"], "tool_error")

    def test_simulator_extension_hard_fail_pattern_applies(self):
        decision = self.grade(log="%Error: something broke\n", xml=PASSING_XML)
        self.assertEqual(decision.status, "ERROR")
        self.assertIn("simulator:verilator", decision.parser["extensions"])

    def test_nonzero_return_code_is_fail_even_with_passing_xml(self):
        decision = self.grade(log="", xml=PASSING_XML, rc=3)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.parser["status_source"], "return_code")
        self.assertIn("exited 3", decision.reason)

    def test_fail_pattern_is_fail(self):
        decision = self.grade(log="TEST FAILED\n", xml=PASSING_XML)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.parser["status_source"], "log_pattern")

    def test_summary_with_a_failure_count_is_fail(self):
        decision = self.grade(log=COCOTB_SUMMARY_FAIL, xml=PASSING_XML)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.parser["status_source"], "log_summary")

    def test_uvm_log_requires_the_report_summary(self):
        decision = self.grade(log="UVM TEST PASSED\n", xml=None, framework="uvm")
        self.assertEqual(decision.status, "FAIL")
        self.assertIn("required pattern missing", decision.reason)

    def test_uvm_log_grades_from_the_error_counts(self):
        clean = "UVM Report Summary\nUVM_ERROR :    0\nUVM_FATAL :    0\nUVM TEST PASSED\n"
        dirty = "UVM Report Summary\nUVM_ERROR :    2\nUVM_FATAL :    0\n"
        self.assertEqual(self.grade(log=clean, xml=None, framework="uvm").status, "PASS")
        failing = self.grade(log=dirty, xml=None, framework="uvm")
        self.assertEqual(failing.status, "FAIL")
        self.assertEqual(failing.parser["status_source"], "log_summary")

    def test_uvm_log_without_evidence_is_unknown(self):
        decision = self.grade(log="UVM Report Summary\n", xml=None, framework="uvm")
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertIn("no positive pass evidence", decision.reason)

    def test_decision_records_policy_fingerprint_and_evidence(self):
        decision = self.grade(log="TEST PASSED\n", xml=PASSING_XML)
        parser = decision.parser
        self.assertEqual(parser["policy"], "cocotb-default")
        self.assertTrue(parser["policy_fingerprint"].startswith("sha256:"))
        self.assertTrue(parser["positive_evidence_required"])
        kinds = {record["kind"] for record in parser["evidence"]}
        self.assertEqual(kinds, {"results_xml", "pass_pattern"})


class StatusRollup(unittest.TestCase):
    def test_aggregate_precedence(self):
        order = ["ERROR", "TIMEOUT", "FAIL", "UNKNOWN", "PASS"]
        for index, worst in enumerate(order):
            stages = [stage("t", status) for status in order[index:]]
            self.assertEqual(aggregate_status(stages), worst)
        self.assertEqual(aggregate_status([]), "PASS")

    def test_exit_codes(self):
        self.assertEqual(
            {status: exit_code_for_status(status) for status in EXIT_CODE_BY_STATUS},
            {"PASS": 0, "FAIL": 1, "ERROR": 2, "TIMEOUT": 124, "UNKNOWN": 5},
        )
        self.assertEqual(exit_code_for_status("SKIP"), 2)


class RegressionRecord(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "dut" / "build" / "runs" / "r"
        self.run_dir.mkdir(parents=True)
        self.flow = make_flow(self.root)
        self.args = Namespace(dry_run=False, verbose=False, quiet=True, cov=False)

    def job(self, item: str, attempt: int, status: str) -> dict:
        return {
            "stage": "sim",
            "item": item,
            "seed": 7,
            "attempt": attempt,
            "status": status,
            "return_code": EXIT_CODE_BY_STATUS.get(status, 0),
            "reason": "process exited 1" if status == "FAIL" else "",
            "duration_sec": 0.5,
            "started_at": "2026-09-01T00:00:00+00:00",
            "ended_at": "2026-09-01T00:00:01+00:00",
            "log": f"dut/build/runs/r/{item}/seed_7/attempt_{attempt}/logs/sim.log",
        }

    def regression(self, jobs: list[dict]) -> dict:
        finals = {}
        for job in jobs:
            finals[job["item"]] = stage(job["item"], job["status"])
        return regression_payload(
            flow=self.flow,
            root=self.root,
            tool=TOOL,
            run_dir=self.run_dir,
            jobs=jobs,
            stages=list(finals.values()),
            args=self.args,
            items=sorted(finals),
            elapsed_sec=1.0,
            versions={TOOL: "5.0"},
            git_metadata={},
            planned_leaves=len(finals),
        )

    def test_pass_after_retry_is_flaky_and_passing(self):
        payload = self.regression([self.job("t_a", 0, "FAIL"), self.job("t_a", 1, "PASS")])
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["failed_tests"], [])
        (flaky,) = payload["flaky_tests"]
        self.assertEqual(flaky["flaky_reason"], "passed_after_retry")
        self.assertEqual((flaky["first_fail_attempt"], flaky["passed_on_attempt"]), (0, 1))
        self.assertEqual(flaky["attempt_count"], 2)
        tests = payload["tests"]
        self.assertEqual((tests["passing"], tests["failing"], tests["flaky"]), (1, 0, 1))
        self.assertEqual(payload["rerun_commands"], [flaky["rerun"]])

    def test_fail_after_retry_is_failed_with_every_attempt(self):
        payload = self.regression([self.job("t_a", 0, "FAIL"), self.job("t_a", 1, "FAIL")])
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["flaky_tests"], [])
        (failed,) = payload["failed_tests"]
        self.assertEqual(failed["attempt_count"], 2)
        self.assertEqual([a["attempt"] for a in failed["attempts"]], [0, 1])
        self.assertEqual(failed["failure_buckets"][0]["kind"], "unknown")
        (bucket,) = payload["failure_buckets"]
        self.assertEqual((bucket["kind"], bucket["count"]), ("unknown", 1))
        self.assertEqual(bucket["affected"][0]["item"], "t_a")

    def test_rerun_command_selects_the_framework_of_the_run(self):
        for framework in ("cocotb", "uvm"):
            with self.subTest(framework=framework):
                self.flow = make_flow(self.root, framework)
                payload = self.regression([self.job("t_a", 0, "FAIL")])
                (failed,) = payload["failed_tests"]
                self.assertIn(f"--framework {framework} ", failed["rerun"])

    def test_formal_rerun_command_selects_the_mode_and_no_framework(self):
        self.flow = make_flow(self.root, "formal")
        self.args.mode = "formal"
        payload = self.regression([self.job("t_a", 0, "FAIL")])
        (failed,) = payload["failed_tests"]
        self.assertIn("--mode formal ", failed["rerun"])
        self.assertNotIn("--framework", failed["rerun"])

    def test_skipped_leaf_is_outside_total_and_not_failed(self):
        payload = self.regression([self.job("t_a", 0, "FAIL"), self.job("t_b", 0, "SKIP")])
        tests = payload["tests"]
        self.assertEqual((tests["total"], tests["skipped"], tests["failing"]), (1, 1, 1))
        self.assertEqual([r["item"] for r in payload["failed_tests"]], ["t_a"])


class JunitOwnership(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "dut" / "build" / "runs" / "r"
        self.leaf = self.run_dir / "t_a" / "seed_7" / "attempt_0"
        self.leaf.mkdir(parents=True)
        self.flow = make_flow(self.root)

    def synthesize(self, result: StageResult) -> Path:
        path = ensure_leaf_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            result=result,
            leaf_dir=self.leaf,
        )
        self.assertEqual(path, self.leaf / "results" / "results.xml")
        return path

    def test_native_file_is_never_touched(self):
        xml_path = self.leaf / "results" / "results.xml"
        xml_path.parent.mkdir()
        xml_path.write_text(PASSING_XML, encoding="utf-8")
        result = stage("t_a", "FAIL", metadata={"seed": 7})
        self.assertIsNone(
            ensure_leaf_junit(
                flow=self.flow,
                root=self.root,
                run_dir=self.run_dir,
                tool=TOOL,
                result=result,
                leaf_dir=self.leaf,
            )
        )
        self.assertEqual(xml_path.read_text(encoding="utf-8"), PASSING_XML)
        self.assertFalse(is_generated_junit(xml_path))

    def test_synthesized_file_carries_the_producer_marker_and_the_status_node(self):
        expected = {
            "PASS": (None, None),
            "FAIL": ("failure", "sim_failure"),
            "ERROR": ("error", "tool_error"),
            "TIMEOUT": ("error", "timeout"),
            "UNKNOWN": ("error", "unknown"),
            "SKIP": ("skipped", None),
        }
        for status, (tag, type_attr) in expected.items():
            with self.subTest(status=status):
                shutil.rmtree(self.leaf / "results", ignore_errors=True)
                result = stage("t_a", status, metadata={"seed": 7}, reason=f"{status} reason")
                path = self.synthesize(result)
                self.assertTrue(is_generated_junit(path))
                suites = ET.parse(path).getroot()
                case = suites.find("./testsuite/testcase")
                self.assertEqual(case.get("name"), "t_a[seed=7]")
                producer = [
                    prop.get("value")
                    for prop in suites.iter("property")
                    if prop.get("name") == "producer"
                ]
                self.assertEqual(producer, [PRODUCER])
                nodes = [child for child in case if child.tag in {"failure", "error", "skipped"}]
                if tag is None:
                    self.assertEqual(nodes, [])
                else:
                    (node,) = nodes
                    self.assertEqual(node.tag, tag)
                    self.assertEqual(node.get("type"), type_attr)

    def test_bucket_kind_names_the_failure_type(self):
        result = stage(
            "t_a",
            "ERROR",
            metadata={"seed": 7},
            failure_buckets=[{"kind": "compile_error", "signature": "x", "count": 1}],
        )
        node = ET.parse(self.synthesize(result)).getroot().find("./testsuite/testcase/error")
        self.assertEqual(node.get("type"), "compile_error")

    def test_the_named_record_defaults_to_the_leaf_and_can_be_the_run(self):
        result = stage("t_a", "ERROR", metadata={"seed": 7}, reason="environment_error: lost")
        for override, expected in (
            (None, "dut/build/runs/r/t_a/seed_7/attempt_0/result.json"),
            (self.run_dir / "result.json", "dut/build/runs/r/result.json"),
        ):
            with self.subTest(expected=expected):
                shutil.rmtree(self.leaf / "results", ignore_errors=True)
                path = ensure_leaf_junit(
                    flow=self.flow,
                    root=self.root,
                    run_dir=self.run_dir,
                    tool=TOOL,
                    result=result,
                    leaf_dir=self.leaf,
                    result_json=override,
                )
                assert path is not None
                suites = ET.parse(path).getroot()
                recorded = [
                    prop.get("value")
                    for prop in suites.iter("property")
                    if prop.get("name") == "result_json"
                ]
                self.assertEqual(recorded, [expected])
                self.assertIn(
                    f"result_json: {expected}",
                    suites.findtext("./testsuite/testcase/system-out", ""),
                )

    def graded(self, result: StageResult, native: str | None = PASSING_XML) -> Path | None:
        """`ensure_graded_junit` over `native` as the leaf's framework-written results.xml."""
        xml_path = self.leaf / "results" / "results.xml"
        if native is not None:
            xml_path.parent.mkdir(exist_ok=True)
            xml_path.write_text(native, encoding="utf-8")
        written = ensure_graded_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            result=result,
            leaf_dir=self.leaf,
        )
        if native is not None:
            self.assertEqual(xml_path.read_text(encoding="utf-8"), native)
        return written

    def test_a_non_passing_grade_over_a_passing_native_file_writes_graded_xml(self):
        expected = {
            "FAIL": ("failure", "sim_failure"),
            "ERROR": ("error", "tool_error"),
            "TIMEOUT": ("error", "timeout"),
            "UNKNOWN": ("error", "unknown"),
        }
        for status, (tag, type_attr) in expected.items():
            with self.subTest(status=status):
                result = stage("t_a", status, metadata={"seed": 7}, reason=f"{status} reason")
                path = self.graded(result)
                self.assertEqual(path, self.leaf / "results" / "graded.xml")
                assert path is not None
                self.assertTrue(is_generated_junit(path))
                (case,) = ET.parse(path).getroot().iter("testcase")
                self.assertEqual(case.get("name"), "t_a[seed=7]")
                (node,) = [child for child in case if child.tag in {"failure", "error"}]
                self.assertEqual(
                    (node.tag, node.get("type"), node.get("message")),
                    (tag, type_attr, f"{status} reason"),
                )

    def test_a_native_file_that_does_not_parse_gets_graded_xml(self):
        result = stage("t_a", "UNKNOWN", metadata={"seed": 7}, reason="malformed")
        path = self.graded(result, native="<testsuites><testsuite")
        assert path is not None
        self.assertIsNotNone(ET.parse(path).getroot().find("./testsuite/testcase/error"))

    def test_a_native_file_that_records_the_failure_gets_no_graded_xml(self):
        for native in (FAILING_XML, ERRORED_XML):
            with self.subTest(native=native[-60:]):
                result = stage("t_a", "FAIL", metadata={"seed": 7})
                self.assertIsNone(self.graded(result, native=native))
                self.assertFalse((self.leaf / "results" / "graded.xml").exists())

    def test_a_passing_or_skipped_grade_gets_no_graded_xml(self):
        for status in ("PASS", "SKIP"):
            with self.subTest(status=status):
                self.assertIsNone(self.graded(stage("t_a", status, metadata={"seed": 7})))
                self.assertFalse((self.leaf / "results" / "graded.xml").exists())

    def test_a_synthesized_or_absent_results_xml_gets_no_graded_xml(self):
        result = stage("t_a", "FAIL", metadata={"seed": 7})
        self.assertIsNone(self.graded(result, native=None))
        self.synthesize(result)
        self.assertIsNone(self.graded(result, native=None))
        self.assertFalse((self.leaf / "results" / "graded.xml").exists())

    def test_a_stale_graded_xml_is_removed_once_the_grade_agrees(self):
        graded_path = self.leaf / "results" / "graded.xml"
        failing = stage("t_a", "FAIL", metadata={"seed": 7})
        for agreeing, native in (
            (stage("t_a", "PASS", metadata={"seed": 7}), PASSING_XML),
            (failing, FAILING_XML),
        ):
            with self.subTest(status=agreeing.status, native=native[-60:]):
                self.assertIsNotNone(self.graded(failing))
                self.assertIsNone(self.graded(agreeing, native=native))
                self.assertFalse(graded_path.exists())

    def test_a_graded_xml_without_the_marker_is_left_alone(self):
        graded_path = self.leaf / "results" / "graded.xml"
        graded_path.parent.mkdir()
        graded_path.write_text(PASSING_XML, encoding="utf-8")
        for status in ("FAIL", "PASS"):
            with self.subTest(status=status):
                self.assertIsNone(self.graded(stage("t_a", status, metadata={"seed": 7})))
                self.assertEqual(graded_path.read_text(encoding="utf-8"), PASSING_XML)

    def test_leafless_failing_run_gets_a_stage_file_in_precedence_order(self):
        stages = [
            stage(None, "FAIL", stage="flist"),
            stage(None, "ERROR", stage="hdl_compile"),
        ]
        path = materialize_stage_junit(
            flow=self.flow, root=self.root, run_dir=self.run_dir, tool=TOOL, stages=stages
        )
        self.assertEqual(path, self.run_dir / "results" / "results.xml")
        case = ET.parse(path).getroot().find("./testsuite/testcase")
        self.assertEqual(case.get("name"), "hdl_compile")
        self.assertIsNotNone(case.find("error"))
        self.assertEqual(stages[1].artifacts["results_xml"], "dut/build/runs/r/results/results.xml")

    def test_passing_run_removes_a_stale_marked_file_and_keeps_a_native_one(self):
        run_xml = self.run_dir / "results" / "results.xml"
        materialize_stage_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            stages=[stage(None, "FAIL", stage="flist")],
        )
        self.assertTrue(is_generated_junit(run_xml))
        self.assertIsNone(
            materialize_stage_junit(
                flow=self.flow,
                root=self.root,
                run_dir=self.run_dir,
                tool=TOOL,
                stages=[stage(None, "PASS", stage="flist")],
            )
        )
        self.assertFalse(run_xml.exists())
        run_xml.parent.mkdir(exist_ok=True)
        run_xml.write_text(PASSING_XML, encoding="utf-8")
        self.assertIsNone(
            materialize_stage_junit(
                flow=self.flow,
                root=self.root,
                run_dir=self.run_dir,
                tool=TOOL,
                stages=[stage(None, "FAIL", stage="flist")],
            )
        )
        self.assertEqual(run_xml.read_text(encoding="utf-8"), PASSING_XML)

    def test_an_executed_leaf_suppresses_the_stage_file(self):
        stages = [stage(None, "ERROR", stage="hdl_compile"), stage("t_a", "FAIL")]
        self.assertIsNone(
            materialize_stage_junit(
                flow=self.flow, root=self.root, run_dir=self.run_dir, tool=TOOL, stages=stages
            )
        )


class JunitReport(unittest.TestCase):
    """The CI-facing `report/junit.xml`: testlist identity, failure message, log tail."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "dut" / "build" / "runs" / "r"
        self.leaf = self.run_dir / "t_a" / "seed_7" / "attempt_0"
        self.log = self.leaf / "logs" / "t_a.log"
        self.log.parent.mkdir(parents=True)
        self.flow = make_flow(self.root)

    def leaf_result(self, status: str, **extra) -> StageResult:
        extra.setdefault("metadata", {"seed": 7, "attempt": 0})
        return stage(
            "t_a", status, target="dual", log=str(self.log.relative_to(self.root)), **extra
        )

    def report(self, result: StageResult, failures: tuple[str, ...] = ()) -> ET.Element:
        path = write_report_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            result=result,
            directory=self.leaf,
            name="t_a",
            result_json=self.leaf / "result.json",
            failures=failures,
        )
        self.assertEqual(path, self.leaf / "report" / "junit.xml")
        assert path is not None
        self.assertTrue(is_generated_junit(path))
        (case,) = ET.parse(path).getroot().iter("testcase")
        return case

    def test_the_case_is_named_by_its_entry_and_carries_the_seed(self):
        self.log.write_text("only line\n", encoding="utf-8")
        case = self.report(self.leaf_result("PASS"))
        self.assertEqual((case.get("classname"), case.get("name")), ("fixture.cocotb.dual", "t_a"))
        self.assertEqual([child.tag for child in case], ["system-out"])
        out = case.findtext("system-out", "").splitlines()
        self.assertEqual(out[0], "seed: 7")
        self.assertIn("log: dut/build/runs/r/t_a/seed_7/attempt_0/logs/t_a.log", out)
        self.assertNotIn("only line", out)

    def test_a_failure_takes_the_first_message_and_ends_with_the_log_tail(self):
        self.log.write_text("".join(f"line {n}\n" for n in range(300)), encoding="utf-8")
        result = self.leaf_result("FAIL", reason="1 testcase failure/error node(s)")
        case = self.report(result, ("TypeError: bad width", "second message"))
        failure = case.find("failure")
        assert failure is not None
        self.assertEqual(
            (failure.get("message"), failure.get("type")), ("TypeError: bad width", "sim_failure")
        )
        self.assertEqual(
            (failure.text or "").splitlines(),
            ["1 testcase failure/error node(s)", "TypeError: bad width", "second message"],
        )
        out = case.findtext("system-out", "").splitlines()
        self.assertIn(
            f"last {REPORT_TAIL_LINES} lines of dut/build/runs/r/t_a/seed_7/attempt_0/logs/t_a.log:",
            out,
        )
        self.assertEqual(out[-REPORT_TAIL_LINES:], [f"line {n}" for n in range(100, 300)])

    def test_without_a_failure_message_the_reason_is_the_message(self):
        result = self.leaf_result("TIMEOUT", reason="exceeded timeout of 60s")
        error = self.report(result).find("error")
        assert error is not None
        self.assertEqual(
            (error.get("message"), error.get("type")), ("exceeded timeout of 60s", "timeout")
        )
        self.assertIsNone(error.text)

    def test_the_tail_of_a_large_log_starts_on_a_whole_line(self):
        width = 100
        count = 2 * REPORT_TAIL_BYTES // width
        lines = [f"{n:0{width - 1}d}" for n in range(count)]
        self.log.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        out = self.report(self.leaf_result("FAIL")).findtext("system-out", "").splitlines()
        self.assertEqual(out[-REPORT_TAIL_LINES:], lines[-REPORT_TAIL_LINES:])

    def test_log_text_is_made_safe_for_xml(self):
        self.log.write_text("\x1b[31mred\x1b[0m\x00 tail\n", encoding="utf-8")
        out = self.report(self.leaf_result("FAIL", reason="bell \x07")).findtext("system-out", "")
        self.assertEqual(out.splitlines()[-1], "red tail")

    def test_a_log_url_base_links_the_log(self):
        with mock.patch.object(junit, "LOG_URL_BASE", "https://ci.example/job/1/artifact/"):
            out = self.report(self.leaf_result("PASS")).findtext("system-out", "")
        self.assertIn(
            "log_url: https://ci.example/job/1/artifact/dut/build/runs/r/t_a/seed_7/attempt_0/logs/t_a.log",
            out.splitlines(),
        )

    def test_a_report_without_the_marker_is_left_alone(self):
        path = self.leaf / "report" / "junit.xml"
        path.parent.mkdir()
        path.write_text(PASSING_XML, encoding="utf-8")
        written = write_report_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            result=self.leaf_result("FAIL"),
            directory=self.leaf,
            name="t_a",
            result_json=self.leaf / "result.json",
        )
        self.assertIsNone(written)
        self.assertEqual(path.read_text(encoding="utf-8"), PASSING_XML)

    def test_a_test_planned_with_several_seeds_is_named_by_seed_index(self):
        plan = [
            {"id": 0, "stage": "sim", "item": "t_a", "seed": 5},
            {"id": 1, "stage": "sim", "item": "t_b", "seed": 9},
            {"id": 2, "stage": "sim", "item": "t_b", "seed": 3},
            {"id": 3, "stage": "formal", "item": "t_a", "seed": 1},
        ]
        self.assertEqual(report_case_names(plan), {0: "t_a", 1: "t_b[0]", 2: "t_b[1]", 3: "t_a"})

    def test_a_leafless_failing_run_mirrors_its_stage_case_with_the_stage_log(self):
        compile_log = self.run_dir / "stages" / "hdl_compile" / "logs" / "hdl_compile.log"
        compile_log.parent.mkdir(parents=True)
        compile_log.write_text("Error-[SE] syntax error\n", encoding="utf-8")
        failing = stage(
            None, "ERROR", stage="hdl_compile", log=str(compile_log.relative_to(self.root))
        )
        materialize_stage_junit(
            flow=self.flow, root=self.root, run_dir=self.run_dir, tool=TOOL, stages=[failing]
        )
        report = self.run_dir / "report" / "junit.xml"
        (case,) = ET.parse(report).getroot().iter("testcase")
        self.assertEqual(
            (case.get("classname"), case.get("name")), ("fixture.cocotb.default", "hdl_compile")
        )
        self.assertEqual(
            case.findtext("system-out", "").splitlines()[-1], "Error-[SE] syntax error"
        )
        materialize_stage_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            stages=[stage(None, "PASS", stage="hdl_compile")],
        )
        self.assertFalse(report.exists())

    def test_an_interrupted_run_mirrors_its_run_case(self):
        materialize_interruption_junit(
            flow=self.flow,
            root=self.root,
            run_dir=self.run_dir,
            tool=TOOL,
            interruption={"reason": "SIGINT received"},
            progress={"completed_count": 1, "expected_count": 3},
        )
        (case,) = ET.parse(self.run_dir / "report" / "junit.xml").getroot().iter("testcase")
        error = case.find("error")
        assert error is not None
        self.assertEqual(case.get("name"), "run")
        self.assertEqual(error.get("type"), "interruption")


class LeafJunitRunStage(unittest.TestCase):
    """A cocotb `sim` leaf through `run_stage`, with a `noop` stage whose note is the log."""

    @classmethod
    def setUpClass(cls):
        cls.policies = validate_parser_registry(REPO_ROOT)
        cls.simulators = load_simulators(REPO_ROOT)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.results = self.root / "run" / "t_a" / "results"

    def run_leaf(
        self, log: str, native: str, *, debug: bool = False, entry: TestEntry | None = None
    ) -> StageResult:
        """Grade `t_a`, or `entry`, with `native` as the results.xml its framework wrote.

        `debug` runs the leaf as a wave-debug rerun, whose framework writes under `debug/`.
        """
        framework_dir = self.results.with_name("debug") if debug else self.results
        framework_dir.mkdir(parents=True, exist_ok=True)
        (framework_dir / "results.xml").write_text(native, encoding="utf-8")
        raw = {"native": {"stages": {"sim": {"kind": "noop", "note": log}}}}
        flow = make_flow(self.root, raw=raw)
        catalog = TestCatalog(
            path=None, groups={}, tests={"t_a": entry or TestEntry(name="t_a", module="t_a")}
        )
        args = Namespace(
            dry_run=False,
            quiet=True,
            verbose=False,
            timeout=None,
            ui="plain",
            seed=None,
            sim_jobs=1,
            cov=False,
            waves=None,
            _wave_debug_rerun=debug,
        )
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return stages.run_stage(
                flow,
                self.root,
                raw,
                catalog,
                "sim",
                "t_a",
                args,
                TOOL,
                self.root / "run",
                self.simulators,
                self.policies,
            )

    def test_a_log_fail_pattern_over_a_passing_cocotb_file_publishes_graded_xml(self):
        result = self.run_leaf("TEST FAILED\n", PASSING_XML)
        self.assertEqual(result.status, "FAIL", result.reason)
        self.assertEqual(result.parser["status_source"], "log_pattern")
        native = self.results / "results.xml"
        self.assertEqual(native.read_text(encoding="utf-8"), PASSING_XML)
        self.assertEqual(result.artifacts["results_xml"], "run/t_a/results/results.xml")
        graded = self.results / "graded.xml"
        self.assertTrue(is_generated_junit(graded))
        (case,) = ET.parse(graded).getroot().iter("testcase")
        self.assertEqual(case.get("name"), "t_a[seed=1]")
        failure = case.find("failure")
        assert failure is not None
        self.assertEqual(failure.get("type"), "sim_failure")
        self.assertEqual(failure.get("message"), result.reason)

    def test_a_rerun_removes_the_previous_graded_xml_before_the_leaf_runs(self):
        self.assertEqual(self.run_leaf("TEST FAILED\n", PASSING_XML).status, "FAIL")
        self.assertTrue((self.results / "graded.xml").is_file())
        with mock.patch.object(stages, "ensure_graded_junit", lambda **_: None):
            result = self.run_leaf("TEST PASSED\n", PASSING_XML)
        self.assertEqual(result.status, "PASS", result.reason)
        self.assertFalse((self.results / "graded.xml").exists())

    def test_a_failure_the_cocotb_file_records_publishes_no_graded_xml(self):
        result = self.run_leaf("TEST FAILED\n", FAILING_XML)
        self.assertEqual(result.status, "FAIL")
        self.assertFalse((self.results / "graded.xml").exists())

    def test_a_wave_debug_rerun_keeps_its_framework_file_outside_results(self):
        leaf = self.results.parent
        self.assertEqual(stages.framework_results_dir(leaf, Namespace()), leaf / "results")
        rerun = Namespace(_wave_debug_rerun=True)
        self.assertEqual(stages.framework_results_dir(leaf, rerun), leaf / "debug")

    def test_a_wave_debug_rerun_grades_from_its_own_framework_file(self):
        result = self.run_leaf("TEST PASSED\n", FAILING_XML, debug=True)
        self.assertEqual(result.status, "FAIL", result.reason)
        self.assertEqual(result.parser["status_source"], "structured_result")
        self.assertFalse(self.results.exists())

    def test_a_wave_debug_rerun_writes_nothing_under_results(self):
        result = self.run_leaf("TEST FAILED\n", PASSING_XML, debug=True)
        self.assertEqual(result.status, "FAIL", result.reason)
        self.assertNotIn("results_xml", result.artifacts)
        self.assertFalse(self.results.exists())
        self.assertEqual(
            (self.results.with_name("debug") / "results.xml").read_text(encoding="utf-8"),
            PASSING_XML,
        )

    def test_a_wave_debug_rerun_matches_its_expected_failure_from_its_own_framework_file(self):
        entry = TestEntry(
            name="t_a", module="t_a", expect_fail="a filed defect", expect_fail_match="^boom$"
        )
        result = self.run_leaf("TEST PASSED\n", FAILING_XML, debug=True, entry=entry)
        self.assertEqual(result.status, "PASS", result.reason)
        record = result.metadata["expected_fail"]
        self.assertEqual(record["observed_failures"], ["boom"])
        self.assertEqual(record["matched_failure"], "boom")


class VcsXceliumSimResultsDir(unittest.TestCase):
    """The results directory the VCS and Xcelium sim stages create for a leaf."""

    STAGES = (("vcs_sim", "_vcs_resolve_build"), ("xcelium_sim", "_xcelium_resolve_build"))

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def sim(self, stage_name: str, resolver: str, *, debug: bool) -> Path:
        leaf = self.root / stage_name / ("rerun" if debug else "graded")
        catalog = TestCatalog(
            path=None, groups={}, tests={"t_a": TestEntry(name="t_a", module="t_a")}
        )
        args = Namespace(
            dry_run=False,
            quiet=True,
            verbose=False,
            timeout=None,
            ui="plain",
            run_mode=None,
            cov=False,
            _wave_debug_rerun=debug,
        )
        info = {
            "simv": "simv",
            "vcs_cfg": {},
            "xcelium_cfg": {},
            "snapshot": "snapshot",
            "build_dir": self.root / "build",
        }
        with (
            mock.patch.object(stages, resolver, return_value=info),
            mock.patch.object(stages, "_wave_format", return_value=""),
            mock.patch.object(stages, "run_subprocess", return_value=0),
            redirect_stdout(io.StringIO()),
        ):
            getattr(stages, stage_name)(
                make_flow(self.root, framework="uvm"),
                self.root,
                {},
                catalog,
                "t_a",
                args,
                leaf,
                leaf / "t_a.log",
                leaf / "t_a.sh",
                leaf / "t_a.env",
                1,
                test_args=[],
            )
        return leaf

    def test_a_wave_debug_rerun_creates_debug_instead_of_results(self):
        for stage_name, resolver in self.STAGES:
            for debug, created, absent in ((False, "results", "debug"), (True, "debug", "results")):
                with self.subTest(stage=stage_name, debug=debug):
                    leaf = self.sim(stage_name, resolver, debug=debug)
                    self.assertTrue((leaf / created).is_dir())
                    self.assertFalse((leaf / absent).exists())


if __name__ == "__main__":
    unittest.main()
