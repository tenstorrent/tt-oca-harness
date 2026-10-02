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

import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.config import load_simulators  # noqa: E402
from runlib.junit import (  # noqa: E402
    PRODUCER,
    ensure_leaf_junit,
    is_generated_junit,
    materialize_stage_junit,
)
from runlib.logparse import parse_stage_result, validate_parser_registry  # noqa: E402
from runlib.models import Dut, StageResult  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
