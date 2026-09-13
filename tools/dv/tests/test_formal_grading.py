# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for formal result grading: the SymbiYosys task-status policy over recorded sby
runs, the cover-reachability and exit-code rules, the per-app evidence hook, the policy and
hook validation, the `formal` object in the result payloads, and the unchanged simulation
result contract.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import copy
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import results, stages  # noqa: E402
from runlib.config import (  # noqa: E402
    load_simulators,
    validate_formal_evidence_hook,
    validate_native_config_shape,
)
from runlib.formal import (  # noqa: E402
    PROPERTY_COUNTERS,
    formal_summary,
    grade_formal_stage,
    render_evidence_path,
)
from runlib.logparse import (  # noqa: E402
    resolved_parser_policy,
    validate_formal_policy,
    validate_parser_extensions,
    validate_parser_registry,
)
from runlib.models import ConfigError, Dut, StageResult, TestCatalog, TestEntry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "formal" / "sby"
DTP_DV_ROOT = REPO_ROOT / "hw/sys/dtp/dv"

SIM_STAGE_KEYS = {
    "name",
    "item",
    "status",
    "return_code",
    "duration_sec",
    "started_at",
    "ended_at",
    "log",
    "artifacts",
    "failure_buckets",
    "reason",
    "parser",
    "metadata",
    "target",
}
SIM_RESULT_KEYS = {
    "schema_version",
    "flow",
    "kind",
    "description",
    "framework",
    "visibility",
    "runnability",
    "license",
    "tool",
    "tool_version",
    "executor",
    "label",
    "status",
    "exit_code",
    "dry_run",
    "generated_at",
    "run_dir",
    "items",
    "overrides",
    "tests",
    "coverage",
    "git",
    "tool_versions",
    "stages",
    "targets",
}


def make_flow(framework: str, raw: dict | None = None, tools: list[str] | None = None) -> Dut:
    return Dut(
        name="dtp",
        kind="fv" if framework == "formal" else "dv",
        description="unit-test flow",
        framework=framework,
        visibility="public",
        runnability="contributor",
        license="none",
        root="hw/sys/dtp/dv",
        default_tool=(tools or ["sby"])[0],
        tools=tools or ["sby"],
        path=DTP_DV_ROOT / f"dtp_{framework}_cfg.toml",
        raw=raw or {},
        frameworks=[framework],
        default_framework=framework,
    )


def stage_result(
    stage: str,
    status: str,
    *,
    item: str | None = None,
    formal: dict | None = None,
    target: str | None = None,
) -> StageResult:
    return StageResult(
        stage=stage,
        item=item,
        status=status,
        return_code=0 if status == "PASS" else 1,
        duration_sec=1.5,
        started_at="2026-09-13T00:00:00+00:00",
        ended_at="2026-09-13T00:00:01+00:00",
        log=f"run/{stage}.log",
        artifacts={},
        failure_buckets=[],
        reason="unit",
        parser=None,
        metadata={},
        target=target,
        formal=formal,
    )


class GradingBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulators = load_simulators(REPO_ROOT)
        cls.policies = validate_parser_registry(REPO_ROOT)

    def grade(
        self,
        stage_dir: Path,
        *,
        item: str = "toy_fpv",
        return_code: int = 0,
        tool: str = "sby",
        app_table: dict | None = None,
        simulators: dict | None = None,
    ):
        return grade_formal_stage(
            root=REPO_ROOT,
            tool=tool,
            simulators=simulators if simulators is not None else self.simulators,
            policies=self.policies,
            item=item,
            app_name="fpv",
            app_table=app_table or {},
            cwd=stage_dir,
            stage_dir=stage_dir,
            run_dir=stage_dir.parent.parent if stage_dir.parent.name == "stages" else stage_dir,
            log_path=stage_dir / "logs" / f"{item}.log",
            return_code=return_code,
        )

    def counters(self, decision) -> dict[str, int]:
        return {counter: decision.formal[counter] for counter in PROPERTY_COUNTERS}


class SbyFixtureGradingTest(GradingBase):
    """Each fixture is a recorded sby run: the runner log plus the task work directories."""

    def test_pass_grades_from_task_lines_and_counts_properties(self) -> None:
        decision = self.grade(FIXTURES / "pass")
        self.assertEqual(decision.status, "PASS")
        self.assertEqual(decision.failure_buckets, [])
        self.assertEqual(
            self.counters(decision),
            {"proven": 1, "failed": 0, "inconclusive": 0, "covered": 2, "unreached": 0},
        )
        self.assertEqual(
            [(task["name"], task["mode"], task["status"]) for task in decision.formal["tasks"]],
            [("bmc", "bmc", "PASS"), ("cover", "cover", "PASS"), ("prove", "prove", "PASS")],
        )
        self.assertEqual(decision.parser["policy"], "sby-summary")
        self.assertEqual(decision.parser["status_source"], "task_status")

    def test_counterexample_is_fail_even_when_the_process_exits_zero(self) -> None:
        decision = self.grade(FIXTURES / "fail", return_code=0)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["formal_fail"])
        self.assertIn("bmc FAIL", decision.reason)
        self.assertEqual(decision.formal["failed"], 1)
        self.assertTrue(
            any("failed assertion" in record["message"] for record in decision.evidence)
        )

    def test_unreached_cover_fails_the_item(self) -> None:
        decision = self.grade(FIXTURES / "unreached", return_code=2)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.formal["unreached"], 1)
        self.assertEqual(decision.formal["covered"], 2)
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["formal_fail"])

    def test_induction_counterexample_is_unknown_not_failed(self) -> None:
        decision = self.grade(FIXTURES / "unknown", return_code=4)
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["unknown"])
        self.assertEqual(decision.formal["failed"], 0)
        self.assertEqual(decision.formal["inconclusive"], 1)

    def test_sby_timeout_grades_timeout(self) -> None:
        decision = self.grade(FIXTURES / "timeout", return_code=8)
        self.assertEqual(decision.status, "TIMEOUT")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["timeout"])
        self.assertEqual([task["name"] for task in decision.formal["tasks"]], ["toy_fpv"])

    def test_tool_error_grades_error(self) -> None:
        decision = self.grade(FIXTURES / "error", return_code=16)
        self.assertEqual(decision.status, "ERROR")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["tool_error"])

    def test_dtp_worked_example_counts_every_property_once(self) -> None:
        decision = self.grade(FIXTURES / "dtp", item="dtp")
        self.assertEqual(decision.status, "PASS")
        self.assertEqual(
            self.counters(decision),
            {"proven": 11, "failed": 0, "inconclusive": 0, "covered": 6, "unreached": 0},
        )
        self.assertEqual(len(decision.formal["tasks"]), 3)


class GradingRulesTest(GradingBase):
    def test_non_zero_exit_with_passing_evidence_is_unknown(self) -> None:
        decision = self.grade(FIXTURES / "pass", return_code=3)
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertEqual(decision.parser["status_source"], "return_code")
        self.assertIn("exited 3", decision.reason)

    def test_missing_evidence_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            (stage_dir / "logs").mkdir()
            (stage_dir / "logs" / "toy_fpv.log").write_text("SBY 00:00:00 starting\n")
            decision = self.grade(stage_dir, return_code=0)
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["unknown"])
        self.assertEqual(decision.formal["tasks"], [])
        self.assertIn("no formal task evidence", decision.reason)

    def test_hard_fail_pattern_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            (stage_dir / "logs").mkdir()
            (stage_dir / "logs" / "toy_fpv.log").write_text(
                "ERROR: -d and --prefix are mutually exclusive.\n"
            )
            decision = self.grade(stage_dir, return_code=1)
        self.assertEqual(decision.status, "ERROR")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["tool_error"])

    def test_status_files_grade_a_run_whose_log_was_lost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            for task in ("bmc", "cover", "prove"):
                shutil.copytree(
                    FIXTURES / "fail" / f"toy_fpv_{task}", stage_dir / f"toy_fpv_{task}"
                )
            (stage_dir / "logs").mkdir()
            (stage_dir / "logs" / "toy_fpv.log").write_text("")
            decision = self.grade(stage_dir, return_code=0)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(
            [(task["name"], task["status"]) for task in decision.formal["tasks"]],
            [("bmc", "FAIL"), ("cover", "PASS"), ("prove", "FAIL")],
        )
        self.assertTrue(any(record["kind"] == "status_file" for record in decision.evidence))

    def test_unreached_cover_fails_a_run_whose_tasks_all_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            shutil.copytree(FIXTURES / "pass", stage_dir, dirs_exist_ok=True)
            report = stage_dir / "toy_fpv_cover" / "pass_cover.xml"
            text = report.read_text()
            marker = 'id="cov_cnt_two" tracefile="engine_0/trace0.vcd">'
            self.assertIn(marker, text)
            report.write_text(
                text.replace(marker, 'id="cov_cnt_two">\n<failure type="COVER" message="x" />')
            )
            decision = self.grade(stage_dir, return_code=0)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.parser["status_source"], "task_results")
        self.assertEqual(decision.formal["unreached"], 1)
        self.assertEqual(decision.formal["covered"], 1)

    def test_tool_without_policy_or_hook_is_unknown(self) -> None:
        simulators = copy.deepcopy(self.simulators)
        del simulators["sby"]["parser_policy"]
        decision = self.grade(FIXTURES / "pass", simulators=simulators)
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertIn("no grading source", decision.reason)


class EvidenceHookTest(GradingBase):
    HOOK = {
        "summary": "results/summary.txt",
        "pass_patterns": ["^\\S+ proven$", "^\\S+ covered$"],
        "fail_patterns": ["^\\S+ cex$"],
        "inconclusive_patterns": ["^\\S+ undetermined$"],
        "cover_patterns": ["^\\S+ covered$"],
        "unreached_patterns": ["^\\S+ unreachable$"],
    }

    def grade_summary(self, lines: list[str] | None, return_code: int = 0):
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            (stage_dir / "logs").mkdir()
            (stage_dir / "logs" / "toy_fpv.log").write_text("tool log\n")
            if lines is not None:
                (stage_dir / "results").mkdir()
                (stage_dir / "results" / "summary.txt").write_text("\n".join(lines) + "\n")
            return self.grade(
                stage_dir,
                tool="jasper",
                app_table={"evidence": dict(self.HOOK)},
                return_code=return_code,
            )

    def test_pass_lines_grade_pass_and_count(self) -> None:
        decision = self.grade_summary(["ast_a proven", "ast_b proven", "cov_x covered"])
        self.assertEqual(decision.status, "PASS")
        self.assertEqual(decision.parser["policy"], "evidence:fpv")
        self.assertEqual(decision.parser["status_source"], "summary_file")
        self.assertEqual(decision.formal["proven"], 3)
        self.assertEqual(decision.formal["covered"], 1)
        self.assertEqual(decision.formal["tasks"][0]["name"], "fpv")

    def test_fail_line_grades_fail(self) -> None:
        decision = self.grade_summary(["ast_a proven", "ast_b cex"])
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["formal_fail"])
        self.assertEqual(decision.formal["failed"], 1)

    def test_unreachable_cover_grades_fail(self) -> None:
        decision = self.grade_summary(["ast_a proven", "cov_x unreachable"])
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.formal["unreached"], 1)

    def test_inconclusive_line_grades_unknown(self) -> None:
        decision = self.grade_summary(["ast_a proven", "ast_b undetermined"])
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertEqual(decision.formal["inconclusive"], 1)

    def test_missing_summary_is_unknown(self) -> None:
        decision = self.grade_summary(None)
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertIn("missing or empty", decision.reason)

    def test_summary_without_pass_evidence_is_unknown(self) -> None:
        decision = self.grade_summary(["nothing graded here"])
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertIn("no pass evidence", decision.reason)

    def test_non_zero_exit_with_passing_summary_is_unknown(self) -> None:
        decision = self.grade_summary(["ast_a proven"], return_code=1)
        self.assertEqual(decision.status, "UNKNOWN")

    def test_summary_path_renders_placeholders_and_resolves_against_cwd(self) -> None:
        cwd = Path("/work/app")
        self.assertEqual(
            render_evidence_path(
                "{run_dir}/stages/formal/{item}/s.txt", run_dir=Path("/r"), item="x", cwd=cwd
            ),
            Path("/r/stages/formal/x/s.txt"),
        )
        self.assertEqual(
            render_evidence_path("out/{item}.txt", run_dir=Path("/r"), item="x", cwd=cwd),
            Path("/work/app/out/x.txt"),
        )


class PolicyValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = {
            "grader": "formal",
            "task_status_patterns": ["DONE \\((?P<status>[A-Z]+)\\)"],
            "task_results": "sby-junit",
        }

    def test_registry_carries_the_sby_formal_policy(self) -> None:
        policies = validate_parser_registry(REPO_ROOT)
        self.assertEqual(policies["sby-summary"]["grader"], "formal")
        simulators = load_simulators(REPO_ROOT)
        self.assertEqual(simulators["sby"]["parser_policy"], "sby-summary")

    def test_valid_policy_passes(self) -> None:
        validate_formal_policy("unit", self.policy)

    def test_status_group_is_required(self) -> None:
        self.policy["task_status_patterns"] = ["DONE \\(([A-Z]+)\\)"]
        with self.assertRaises(ConfigError) as ctx:
            validate_formal_policy("unit", self.policy)
        self.assertIn("(?P<status>", str(ctx.exception))

    def test_unknown_key_and_bad_results_format_are_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            validate_formal_policy("unit", {**self.policy, "pass_patterns": ["x"]})
        with self.assertRaises(ConfigError):
            validate_formal_policy("unit", {**self.policy, "task_results": "csv"})
        with self.assertRaises(ConfigError):
            validate_formal_policy("unit", {**self.policy, "grader": "sim"})

    def test_formal_policy_is_not_a_simulation_policy(self) -> None:
        flow = make_flow(
            "cocotb", raw={"pass_fail": {"policy": "sby-summary"}}, tools=["verilator"]
        )
        policies = validate_parser_registry(REPO_ROOT)
        with self.assertRaises(ConfigError) as ctx:
            resolved_parser_policy(flow, "verilator", policies, load_simulators(REPO_ROOT))
        self.assertIn("formal grader", str(ctx.exception))


class EvidenceHookValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hook = {
            "summary": "{run_dir}/stages/formal/{item}/summary.txt",
            "pass_patterns": ["proven$"],
            "fail_patterns": ["cex$"],
        }

    def test_valid_hook_passes(self) -> None:
        validate_formal_evidence_hook(self.hook, "unit")

    def test_summary_and_required_patterns(self) -> None:
        with self.assertRaises(ConfigError):
            validate_formal_evidence_hook({**self.hook, "summary": ""}, "unit")
        with self.assertRaises(ConfigError):
            validate_formal_evidence_hook(
                {k: v for k, v in self.hook.items() if k != "fail_patterns"}, "unit"
            )

    def test_bad_regex_unknown_key_and_unknown_placeholder(self) -> None:
        with self.assertRaises(ConfigError):
            validate_formal_evidence_hook({**self.hook, "pass_patterns": ["("]}, "unit")
        with self.assertRaises(ConfigError):
            validate_formal_evidence_hook({**self.hook, "extra": 1}, "unit")
        with self.assertRaises(ConfigError) as ctx:
            validate_formal_evidence_hook({**self.hook, "summary": "{binary}.txt"}, "unit")
        self.assertIn("{binary}", str(ctx.exception))

    def test_hook_is_checked_by_config_validation(self) -> None:
        good = {"formal": {"apps": {"fpv": {"sby": {"script": "dtp.sby", "evidence": self.hook}}}}}
        validate_native_config_shape(make_flow("formal", good), REPO_ROOT)
        bad = copy.deepcopy(good)
        del bad["formal"]["apps"]["fpv"]["sby"]["evidence"]["pass_patterns"]
        with self.assertRaises(ConfigError) as ctx:
            validate_native_config_shape(make_flow("formal", bad), REPO_ROOT)
        self.assertIn("[formal.apps.fpv.sby].evidence", str(ctx.exception))


class GradingSourceValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulators = load_simulators(REPO_ROOT)
        cls.policies = validate_parser_registry(REPO_ROOT)
        cls.licensed = next(
            name
            for name, cfg in sorted(cls.simulators.items())
            if cfg.get("kind") == "formal" and cfg["license_env"]
        )

    def test_sby_app_is_graded_by_the_registry_policy(self) -> None:
        raw = {"formal": {"apps": {"fpv": {"sby": {"script": "dtp.sby"}}}}}
        validate_parser_extensions(make_flow("formal", raw), self.simulators, self.policies)

    def test_backend_without_policy_needs_an_evidence_table(self) -> None:
        tools = ["sby", self.licensed]
        raw = {"formal": {"apps": {"conn": {self.licensed: {"script": "run.tcl"}}}}}
        with self.assertRaises(ConfigError) as ctx:
            validate_parser_extensions(
                make_flow("formal", raw, tools), self.simulators, self.policies
            )
        self.assertIn("no grading source", str(ctx.exception))
        raw["formal"]["apps"]["conn"][self.licensed]["evidence"] = {
            "summary": "summary.txt",
            "pass_patterns": ["proven"],
            "fail_patterns": ["cex"],
        }
        validate_parser_extensions(make_flow("formal", raw, tools), self.simulators, self.policies)

    def test_parser_policy_must_name_a_formal_grader(self) -> None:
        simulators = copy.deepcopy(self.simulators)
        simulators["sby"]["parser_policy"] = "uvm-log"
        with self.assertRaises(ConfigError) as ctx:
            validate_parser_extensions(make_flow("formal"), simulators, self.policies)
        self.assertIn("parser_policy", str(ctx.exception))


class ResultContractTest(unittest.TestCase):
    """The simulation result keeps its exact key set; formal runs add a `formal` object."""

    def test_simulation_stage_dict_has_no_formal_key(self) -> None:
        stage = stage_result("sim", "PASS", item="t", target="default")
        self.assertEqual(set(results._stage_dict(stage)), SIM_STAGE_KEYS)

    def test_formal_stage_dict_adds_the_report(self) -> None:
        report = {"grader": "sby-summary", "tasks": [], "proven": 1}
        stage = stage_result("formal", "PASS", item="dtp_fpv", formal=report)
        payload = results._stage_dict(stage)
        self.assertEqual(set(payload), SIM_STAGE_KEYS - {"target"} | {"formal"})
        self.assertEqual(payload["formal"], report)

    def test_simulation_result_payload_keeps_its_keys(self) -> None:
        flow = make_flow("cocotb", tools=["verilator"])
        stage_list = [
            stage_result("flist", "PASS", target="default"),
            stage_result("sim", "PASS", item="t", target="default"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            payload = results.result_payload(
                flow=flow,
                root=REPO_ROOT,
                tool="verilator",
                run_dir=Path(tmp),
                stages=stage_list,
                dry_run=False,
                items=["t"],
                versions={"python": "3"},
                git_metadata={"commit": "", "branch": "", "dirty": "false"},
            )
        self.assertEqual(set(payload) - {"targets"}, SIM_RESULT_KEYS - {"targets"})
        self.assertNotIn("formal", payload)
        self.assertEqual(payload["tests"]["total"], 1)

    def test_formal_result_payload_adds_totals_and_counts_items(self) -> None:
        flow = make_flow("formal")
        report_a = {
            "grader": "sby-summary",
            "tasks": [{"name": "bmc", "status": "PASS"}, {"name": "cover", "status": "PASS"}],
            "proven": 11,
            "failed": 0,
            "inconclusive": 0,
            "covered": 6,
            "unreached": 0,
        }
        report_b = {
            "grader": "sby-summary",
            "tasks": [{"name": "bmc", "status": "FAIL"}],
            "proven": 0,
            "failed": 1,
            "inconclusive": 1,
            "covered": 0,
            "unreached": 0,
        }
        stage_list = [
            stage_result("formal", "PASS", item="a", formal=report_a),
            stage_result("formal", "FAIL", item="b", formal=report_b),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            payload = results.result_payload(
                flow=flow,
                root=REPO_ROOT,
                tool="sby",
                run_dir=Path(tmp),
                stages=stage_list,
                dry_run=False,
                items=["a", "b"],
                versions={"python": "3"},
                git_metadata={"commit": "", "branch": "", "dirty": "false"},
            )
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["tests"]["total"], 2)
        self.assertEqual(payload["tests"]["passing"], 1)
        self.assertEqual(payload["tests"]["failing"], 1)
        self.assertEqual(
            payload["formal"],
            {
                "proven": 11,
                "failed": 1,
                "inconclusive": 1,
                "covered": 6,
                "unreached": 0,
                "tasks": {"total": 3, "passing": 2, "failing": 1},
            },
        )
        self.assertEqual(payload["coverage"]["enabled"], False)
        fragment = results.fragment_payload(
            flow=flow,
            root=REPO_ROOT,
            tool="sby",
            run_dir=Path("/r"),
            item="a",
            seed=1,
            result=stage_list[0],
        )
        self.assertEqual(fragment["formal"], report_a)

    def test_formal_summary_ignores_ungraded_stages(self) -> None:
        summary = formal_summary([stage_result("formal", "ERROR", item="a")])
        self.assertEqual(summary["tasks"], {"total": 0, "passing": 0, "failing": 0})
        self.assertEqual(summary["proven"], 0)


class RunStageIntegrationTest(unittest.TestCase):
    """`run_stage` grades the formal stage from the evidence sby leaves behind, not from rc."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.simulators = load_simulators(REPO_ROOT)
        cls.policies = validate_parser_registry(REPO_ROOT)

    def run_formal(self, fixture: str, return_code: int) -> StageResult:
        raw = {
            "native": {"stages": {"formal": {"kind": "formal_run"}}},
            "formal": {
                "apps": {"fpv": {"sby": {"cwd": ".", "script": "toy.sby", "args": ["bmc"]}}}
            },
        }
        flow = make_flow("formal", raw)
        catalog = TestCatalog(
            path=None, tests={"toy_fpv": TestEntry(name="toy_fpv", module="fpv")}, groups={}
        )
        args = Namespace(
            dry_run=False,
            quiet=True,
            verbose=False,
            timeout=None,
            proof_depth=None,
            formal_arg=None,
            app=None,
            ui="plain",
            seed=None,
            sim_jobs=1,
            cov=False,
            waves=None,
        )

        def fake_launch(argv, root, log_path, dry_run, script_path, env_path, quiet, **kwargs):
            stage_dir = log_path.parent.parent
            shutil.copytree(FIXTURES / fixture, stage_dir, dirs_exist_ok=True)
            return return_code

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(stages, "run_subprocess", side_effect=fake_launch):
                return stages.run_stage(
                    flow,
                    REPO_ROOT,
                    raw,
                    catalog,
                    "formal",
                    "toy_fpv",
                    args,
                    "sby",
                    Path(tmp),
                    self.simulators,
                    self.policies,
                )

    def test_zero_exit_with_a_counterexample_is_fail(self) -> None:
        result = self.run_formal("fail", 0)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(
            [bucket["kind"] for bucket in result.failure_buckets or []], ["formal_fail"]
        )
        self.assertEqual(result.formal["failed"], 1)
        self.assertEqual(result.parser["policy"], "sby-summary")
        self.assertTrue(result.failure_buckets[0]["examples"][0].endswith("toy_fpv.log"))

    def test_passing_evidence_is_pass(self) -> None:
        result = self.run_formal("pass", 0)
        self.assertEqual(result.status, "PASS")
        self.assertIsNone(result.failure_buckets)
        self.assertEqual(result.formal["covered"], 2)

    def test_dry_run_leaves_the_stage_ungraded(self) -> None:
        raw = {
            "native": {"stages": {"formal": {"kind": "formal_run"}}},
            "formal": {"apps": {"fpv": {"sby": {"script": "toy.sby", "args": ["bmc"]}}}},
        }
        catalog = TestCatalog(
            path=None, tests={"toy_fpv": TestEntry(name="toy_fpv", module="fpv")}, groups={}
        )
        args = Namespace(
            dry_run=True,
            quiet=True,
            verbose=False,
            timeout=None,
            proof_depth=None,
            formal_arg=None,
            app=None,
            ui="plain",
            seed=None,
            sim_jobs=1,
            cov=False,
            waves=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = stages.run_stage(
                make_flow("formal", raw),
                REPO_ROOT,
                raw,
                catalog,
                "formal",
                "toy_fpv",
                args,
                "sby",
                Path(tmp),
                self.simulators,
                self.policies,
            )
        self.assertEqual(result.status, "PASS")
        self.assertIsNone(result.formal)


if __name__ == "__main__":
    unittest.main()
