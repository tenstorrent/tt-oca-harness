# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for formal result grading: the SymbiYosys task-status policy over sby run
evidence synthesized in the shape sby writes it, the cover-reachability and exit-code rules,
the per-app evidence hook, the policy and hook validation, the `formal` object in the result
payloads, and the unchanged simulation result contract.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import results, site, stages  # noqa: E402
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
from runlib.site import load_site_layer, merged_simulators  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# A licensed formal backend reaches the runner as a complete tool table in the site layer; this
# one carries the generic launch template a Tcl-driven tool uses.
LICENSED_SITE = """
schema_version = 1
[simulators.fvtool]
kind = "formal"
binary = "fvtool"
frameworks = ["formal"]
license_env = ["FVTOOL_LICENSE_FILE"]
supports_waves = []
supports_cov = ["formal"]
default_waves = ""
argv = ["{binary}", "{args}", "{script}", "{formal_args}"]
"""


def registry_with_site_backend() -> dict:
    """The checked-in registry with the site-added licensed backend `fvtool` merged in."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "site.toml"
        path.write_text(LICENSED_SITE)
        layer = load_site_layer(REPO_ROOT, {site.SITE_ENV: str(path)})
    assert layer is not None
    return merged_simulators(load_simulators(REPO_ROOT), layer)


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


# sby's exit code for each task status when the task's `expect` option is the default PASS.
SBY_RC = {"PASS": 0, "FAIL": 2, "UNKNOWN": 4, "TIMEOUT": 8, "ERROR": 16}

# JUnit child element sby writes for a property in each state.
JUNIT_CHILD = {
    "PASS": "",
    "FAIL": '\n<failure type="{kind}" message="Property {kind} {prop} failed." />',
    "UNKNOWN": "\n<skipped />",
    "ERROR": '\n<error type="ERROR"/>',
}

Prop = tuple[str, str, str]  # (ASSERT|COVER, property id, PASS|FAIL|UNKNOWN|ERROR)


def sby_task(
    name: str | None,
    mode: str,
    status: str,
    props: list[Prop],
    summary: list[str] | None = None,
) -> dict:
    """One task of an sby run; `name` None is the taskless form whose work directory is the
    `--prefix` itself."""
    return {"name": name, "mode": mode, "status": status, "props": props, "summary": summary or []}


def junit_report(task: dict, sby_name: str) -> str:
    """The JUnit report sby writes per task: a `build execution` row, then one row per property
    with its `type` and `id`; a task that never elaborated gets one typeless error row."""
    name = task["name"] or "default"
    rows: list[str] = []
    if task["status"] == "ERROR" and not task["props"]:
        rows.append(
            f'<testcase classname="{name}" name="{name}" time="0">\n<error type="ERROR"/>\n</testcase>'
        )
    else:
        build = (
            ""
            if task["status"] == "PASS"
            else f'\n<failure type="{task["status"]}" message="Task returned status {task["status"]}." />'
        )
        rows.append(
            f'<testcase classname="{name}" name="build execution" time="0">{build}\n</testcase>'
        )
        for kind, prop, state in task["props"]:
            child = JUNIT_CHILD[state].format(kind=kind, prop=prop)
            rows.append(
                f'<testcase classname="{name}" name="Property {kind} {prop} in top" time="0" '
                f'type="{kind}" location="" id="{prop}">{child}\n</testcase>'
            )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>\n'
        f'<testsuite timestamp="2026-01-01T00:00:00" hostname="host" package="{sby_name}" id="0" '
        f'name="{name}" tests="{len(rows)}" errors="0" failures="0" time="0" skipped="0">\n'
        f'<properties>\n<property name="status" value="{task["status"]}"/>\n</properties>\n'
        + "\n".join(rows)
        + "\n<system-out></system-out>\n<system-err></system-err>\n</testsuite>\n</testsuites>\n"
    )


def record_sby_run(stage_dir: Path, item: str, tasks: list[dict], sby_name: str = "toy") -> None:
    """Write what one `sby --prefix <stage_dir>/<item>` invocation leaves behind: the runner log
    with a `DONE` line per task, and per task the work directory with `status`, `config.sby`,
    and the JUnit report."""
    (stage_dir / "logs").mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for task in tasks:
        workdir = stage_dir / (f"{item}_{task['name']}" if task["name"] else item)
        workdir.mkdir(parents=True, exist_ok=True)
        rc = SBY_RC[task["status"]]
        (workdir / "status").write_text(f"{task['status']} {rc} 0\n")
        (workdir / "config.sby").write_text(
            f"[options]\nmode {task['mode']}\n\n[engines]\nsmtbmc yices\n"
        )
        report = f"{sby_name}_{task['name']}.xml" if task["name"] else f"{sby_name}.xml"
        (workdir / report).write_text(junit_report(task, sby_name))
        prefix = f"SBY 12:00:00 [{workdir}]"
        lines.extend(f"{prefix} summary: {line}" for line in task["summary"])
        lines.append(f"{prefix} DONE ({task['status']}, rc={rc})")
    (stage_dir / "logs" / f"{item}.log").write_text("\n".join(lines) + "\n")


AST = "ASSERT"
COV = "COVER"
COVERS_SKIPPED: list[Prop] = [(COV, "cov_wraps", "UNKNOWN"), (COV, "cov_two", "UNKNOWN")]

# A toy counter with one assertion and two covers: every task passes.
PASS_RUN = [
    sby_task("bmc", "bmc", "PASS", [(AST, "ast_below_ten", "PASS"), *COVERS_SKIPPED]),
    sby_task(
        "cover",
        "cover",
        "PASS",
        [(AST, "ast_below_ten", "UNKNOWN"), (COV, "cov_wraps", "PASS"), (COV, "cov_two", "PASS")],
        ["reached cover statement toy.cov_two at toy.sv:15.5-15.38 step 4"],
    ),
    sby_task("prove", "prove", "PASS", [(AST, "ast_below_ten", "PASS"), *COVERS_SKIPPED]),
]

# A second assertion fails in bmc and prove; sby leaves the other assertion unchecked.
FAIL_PROPS: list[Prop] = [
    (AST, "ast_below_ten", "UNKNOWN"),
    (AST, "ast_below_five", "FAIL"),
    *COVERS_SKIPPED,
]
FAIL_SUMMARY = [
    "engine_0 (smtbmc yices) returned FAIL",
    "counterexample trace: engine_0/trace.vcd",
    "  failed assertion toy.ast_below_five at toy.sv:12.5-12.46 step 7",
]
FAIL_RUN = [
    sby_task("bmc", "bmc", "FAIL", FAIL_PROPS, FAIL_SUMMARY),
    PASS_RUN[1],
    sby_task("prove", "prove", "FAIL", FAIL_PROPS, FAIL_SUMMARY),
]

# A third cover is unreachable, so the cover task fails.
UNREACHED_RUN = [
    PASS_RUN[0],
    sby_task(
        "cover",
        "cover",
        "FAIL",
        [
            (AST, "ast_below_ten", "UNKNOWN"),
            (COV, "cov_fifteen", "FAIL"),
            (COV, "cov_two", "PASS"),
            (COV, "cov_wraps", "PASS"),
        ],
        ["unreached cover statements:", "  toy.cov_fifteen at toy.sv:17.5-17.43"],
    ),
    PASS_RUN[2],
]

# A non-inductive assertion: bmc passes, k-induction returns an induction counterexample that
# sby records as a property failure inside an UNKNOWN task.
UNKNOWN_RUN = [
    sby_task(
        "bmc", "bmc", "PASS", [(AST, "ast_never_fifteen", "PASS"), (COV, "cov_two", "UNKNOWN")]
    ),
    sby_task(
        "prove",
        "prove",
        "UNKNOWN",
        [(AST, "ast_never_fifteen", "FAIL"), (COV, "cov_two", "UNKNOWN")],
        [
            "engine_0 (smtbmc yices) returned pass for basecase",
            "engine_0 (smtbmc yices) returned FAIL for induction",
        ],
    ),
]

# A taskless task file whose solver hits the `timeout` option.
TIMEOUT_RUN = [
    sby_task(
        None,
        "bmc",
        "TIMEOUT",
        [(AST, "ast_no_factors", "UNKNOWN")],
        ["engine_0 (smtbmc yices) did not return a status"],
    )
]

# The Yosys script fails before elaboration.
ERROR_RUN = [
    sby_task("bmc", "bmc", "ERROR", [], ["engine_0 (smtbmc yices) did not return a status"])
]


def dtp_like_run() -> list[dict]:
    """Eleven assertions and six covers over bmc, cover, and prove, as the DTP TAP example."""
    asserts = [f"u_tap.ast_{index}" for index in range(11)]
    covers = [f"u_tap.cov_{index}" for index in range(6)]
    checked_asserts: list[Prop] = [(AST, name, "PASS") for name in asserts]
    skipped_asserts: list[Prop] = [(AST, name, "UNKNOWN") for name in asserts]
    reached_covers: list[Prop] = [(COV, name, "PASS") for name in covers]
    skipped_covers: list[Prop] = [(COV, name, "UNKNOWN") for name in covers]
    return [
        sby_task("bmc", "bmc", "PASS", checked_asserts + skipped_covers),
        sby_task("cover", "cover", "PASS", skipped_asserts + reached_covers),
        sby_task("prove", "prove", "PASS", checked_asserts + skipped_covers),
    ]


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
            run_dir=stage_dir,
            log_path=stage_dir / "logs" / f"{item}.log",
            return_code=return_code,
        )

    def grade_run(self, tasks: list[dict], *, item: str = "toy_fpv", return_code: int = 0, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp)
            record_sby_run(stage_dir, item, tasks)
            return self.grade(stage_dir, item=item, return_code=return_code, **kw)

    def counters(self, decision) -> dict[str, int]:
        return {counter: decision.formal[counter] for counter in PROPERTY_COUNTERS}


class SbyRunGradingTest(GradingBase):
    """Each run is the evidence one sby invocation leaves: the runner log plus the task work
    directories."""

    def test_pass_grades_from_task_lines_and_counts_properties(self) -> None:
        decision = self.grade_run(PASS_RUN)
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
        decision = self.grade_run(FAIL_RUN, return_code=0)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["formal_fail"])
        self.assertIn("bmc FAIL", decision.reason)
        self.assertEqual(
            self.counters(decision),
            {"proven": 0, "failed": 1, "inconclusive": 1, "covered": 2, "unreached": 0},
        )
        self.assertTrue(
            any("failed assertion" in record["message"] for record in decision.evidence)
        )

    def test_unreached_cover_fails_the_item(self) -> None:
        decision = self.grade_run(UNREACHED_RUN, return_code=2)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.formal["unreached"], 1)
        self.assertEqual(decision.formal["covered"], 2)
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["formal_fail"])

    def test_induction_counterexample_is_unknown_not_failed(self) -> None:
        decision = self.grade_run(UNKNOWN_RUN, return_code=4)
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["unknown"])
        self.assertEqual(decision.formal["failed"], 0)
        self.assertEqual(decision.formal["inconclusive"], 1)

    def test_sby_timeout_grades_timeout(self) -> None:
        decision = self.grade_run(TIMEOUT_RUN, return_code=8)
        self.assertEqual(decision.status, "TIMEOUT")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["timeout"])
        self.assertEqual([task["name"] for task in decision.formal["tasks"]], ["toy_fpv"])
        self.assertEqual(decision.formal["inconclusive"], 1)

    def test_tool_error_grades_error(self) -> None:
        decision = self.grade_run(ERROR_RUN, return_code=16)
        self.assertEqual(decision.status, "ERROR")
        self.assertEqual([bucket["kind"] for bucket in decision.failure_buckets], ["tool_error"])
        self.assertEqual(sum(self.counters(decision).values()), 0)

    def test_every_property_is_counted_once_across_tasks(self) -> None:
        decision = self.grade_run(dtp_like_run(), item="dtp")
        self.assertEqual(decision.status, "PASS")
        self.assertEqual(
            self.counters(decision),
            {"proven": 11, "failed": 0, "inconclusive": 0, "covered": 6, "unreached": 0},
        )
        self.assertEqual(len(decision.formal["tasks"]), 3)


class GradingRulesTest(GradingBase):
    def test_non_zero_exit_with_passing_evidence_is_unknown(self) -> None:
        decision = self.grade_run(PASS_RUN, return_code=3)
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
            record_sby_run(stage_dir, "toy_fpv", FAIL_RUN)
            (stage_dir / "logs" / "toy_fpv.log").write_text("")
            decision = self.grade(stage_dir, return_code=0)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(
            [(task["name"], task["status"]) for task in decision.formal["tasks"]],
            [("bmc", "FAIL"), ("cover", "PASS"), ("prove", "FAIL")],
        )
        self.assertTrue(any(record["kind"] == "status_file" for record in decision.evidence))

    def test_unreached_cover_fails_a_run_whose_tasks_all_passed(self) -> None:
        cover = sby_task(
            "cover",
            "cover",
            "PASS",
            [
                (AST, "ast_below_ten", "UNKNOWN"),
                (COV, "cov_wraps", "PASS"),
                (COV, "cov_two", "FAIL"),
            ],
        )
        decision = self.grade_run([PASS_RUN[0], cover, PASS_RUN[2]], return_code=0)
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.parser["status_source"], "task_results")
        self.assertEqual(decision.formal["unreached"], 1)
        self.assertEqual(decision.formal["covered"], 1)

    def test_tool_without_policy_or_hook_is_unknown(self) -> None:
        simulators = copy.deepcopy(self.simulators)
        del simulators["sby"]["parser_policy"]
        decision = self.grade_run(PASS_RUN, simulators=simulators)
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
                tool="fvtool",
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
        cls.simulators = registry_with_site_backend()
        cls.policies = validate_parser_registry(REPO_ROOT)
        cls.licensed = "fvtool"

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

    def run_formal(self, tasks: list[dict], return_code: int) -> StageResult:
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
            record_sby_run(log_path.parent.parent, "toy_fpv", tasks)
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
        result = self.run_formal(FAIL_RUN, 0)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(
            [bucket["kind"] for bucket in result.failure_buckets or []], ["formal_fail"]
        )
        self.assertEqual(result.formal["failed"], 1)
        self.assertEqual(result.parser["policy"], "sby-summary")
        self.assertTrue(result.failure_buckets[0]["examples"][0].endswith("toy_fpv.log"))

    def test_passing_evidence_is_pass(self) -> None:
        result = self.run_formal(PASS_RUN, 0)
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
