# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Tests for the post-report coverage grading shared by the report stage.

The coverage run under test is built here: a Verilator coverage database over one scan
register, its lcov report, the merge manifest the `cov_merge` stage writes, and the DUT's
coverage policy. `finish_run` drives the report stage through `run_stage` and writes the
run-level `result.json` and `regression.json` with the runner's own payload builders, so the
`--waive` and policy-expiry tests re-grade a run the runner produced.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import dataclasses
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.coverage import load_manifest, write_json  # noqa: E402
from runlib.coverage_closure import (  # noqa: E402
    CoverageGrade,
    coverage_run_paths,
    grade_coverage_run,
    parse_coverage_run,
)
from runlib.coverage_policy import load_coverage_policy  # noqa: E402
from runlib.models import ConfigError, Dut, StageResult, TestCatalog  # noqa: E402
from runlib.results import regression_payload, result_payload, write_result  # noqa: E402
from runlib.stages import coverage_stage, run_stage  # noqa: E402

TOOL = "verilator"
DUT = "fixture"
ITEM = "fixture_smoke_test"
TOOL_VERSION = "Verilator 5.050 2026-07-01 rev vUNKNOWN-built20260701"
SUPPORTED_METRICS = ["line", "toggle", "branch"]
BUILD_FINGERPRINT = "0aecd4b109ca"
MANIFEST_GENERATED_AT = "2026-09-01T08:00:00+00:00"
POLICY_REL = Path("dut/cov/config/verilator/coverage_policy.toml")
NATIVE_REL = Path("dut/cov/config/verilator/verilator_native.cfg")
REGRESSION_REL = Path("stages/regress/regression.json")
# Graded file name -> path under the staged root; the report stage writes each of these.
GRADED_FILES = {
    "coverage-details.raw.json": Path("run/cov/report/coverage-details.raw.json"),
    "coverage-details.json": Path("run/cov/report/coverage-details.json"),
    "policy-application.json": Path("run/cov/report/policy-application.json"),
    "summary.json": Path("run/cov/report/summary.json"),
    "coverage.json": Path("run/cov/coverage.json"),
    "cov_report.log": Path("run/stages/cov_report/logs/cov_report.log"),
}
GRADE_WRITES = ("coverage-details.json", "policy-application.json", "summary.json", "coverage.json")
REPORT_FILES = ("coverage-details.raw.json", *GRADE_WRITES[:-1])

# What the built run grades to under the policy below: two toggle points waived or open by
# policy, four more uncovered points unclassified, and the toggle threshold missed.
EXPECTED_METRICS = {"branch": 50.0, "expression": 66.6667, "line": 66.6667, "toggle": 60.0}
EXPECTED_OVERALL = 57.1429
EXPECTED_THRESHOLDS_MET = [True, False]
EXPECTED_HOLES = {"accepted": 1, "open": 5, "native_point_count": 6, "hole_group_count": 2}
EXPECTED_MATCHED = ["toggle-capture_en-rise", "toggle-run_test_idle-rise"]

POLICY_TOML = """\
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

schema_version = 1
dut = "fixture"
scope_epoch = "fixture-v1"

[[thresholds]]
id = "line-effective"
metric_family = "line"
minimum_percent = 50.0

[[thresholds]]
id = "toggle-effective"
metric_family = "toggle"
minimum_percent = 90.0
max_unclassified_points = 0

[[native_files]]
tool = "verilator"
role = "reference"
path = "verilator_native.cfg"
apply_phase = "report"
args = []

[[holes]]
id = "toggle-capture_en-rise"
title = "capture_en never rises"
category = "tied_off"
disposition = "waive"
status = "accepted"
confidence = "high"
rationale = "capture_en is tied low in this configuration."
owner = "fixture-dv"
reviewer = "fixture-dv"
date = "2026-09-01"
[[holes.native]]
tool = "verilator"
metric_family = "toggle"
native_locator = "*|o=scan_ctrl_i.capture_en:0->1|*"

[[holes]]
id = "toggle-run_test_idle-rise"
title = "run_test_idle never rises"
category = "missing_stimulus"
disposition = "cover"
status = "open"
confidence = "medium"
rationale = "No test drives the TAP through Run-Test/Idle."
owner = "fixture-dv"
reviewer = "fixture-dv"
date = "2026-09-01"
issues = ["https://github.com/example/fixture/issues/1"]
[[holes.native]]
tool = "verilator"
metric_family = "toggle"
native_locator = "*|o=scan_ctrl_i.run_test_idle:0->1|*"
"""

SOURCE = "hw/common/ocah_prim/rtl/prim_jtag_scan_reg.sv"
HIERARCHY = "fixture_top.u_dut.u_jtag_intf_unit.*_scan_reg"
# Verilator coverage points as (line, column, type, comment, statement span, count); the page
# is derived from the type. Six toggles, three lines, two branches, three expressions.
COVERAGE_POINTS = [
    (22, 31, "toggle", "scan_ctrl_i.capture_en:0->1", None, 0),
    (22, 31, "toggle", "scan_ctrl_i.capture_en:1->0", None, 0),
    (22, 31, "toggle", "scan_ctrl_i.run_test_idle:0->1", None, 0),
    (22, 31, "toggle", "scan_ctrl_i.chrst_n:0->1", None, 9),
    (22, 31, "toggle", "scan_ctrl_i.chrst_n:1->0", None, 9),
    (22, 31, "toggle", "scan_ctrl_i.rst_n:0->1", None, 9),
    (30, 3, "line", "block", "30", 9),
    (35, 50, "line", "block", "35", 7324),
    (51, 9, "line", "elsif", "51-52", 0),
    (53, 18, "branch", "if", "53-54", 0),
    (53, 19, "branch", "else", None, 90),
    (35, 50, "expr", "(scan_ctrl_i[3]==1 && scan_ctrl_i[4]==1) => 1", None, 0),
    (35, 50, "expr", "(scan_ctrl_i[3]==0) => 0", None, 7324),
    (35, 50, "expr", "(scan_ctrl_i[4]==0) => 0", None, 12564),
]

LCOV_INFO = f"""\
TN:verilator_coverage
SF:{SOURCE}
DA:22,11709
DA:30,9
DA:35,7324
DA:51,0
BRDA:53,0,0,0
BRDA:53,0,1,90
LF:4
LH:3
BRF:2
BRH:1
end_of_record
"""


def coverage_dat() -> str:
    """The merged Verilator coverage database: one `C '<key>' <count>` line per point. A key
    is the point's fields, each written as `\\x01<name>\\x02<value>`."""
    lines = ["# SystemC::Coverage-3"]
    for line, column, kind, comment, span, count in COVERAGE_POINTS:
        fields = [
            ("f", SOURCE),
            ("l", str(line)),
            ("n", str(column)),
            ("t", kind),
            ("page", f"v_{kind}/prim_jtag_scan_reg_"),
            ("o", comment),
            *([("S", span)] if span else []),
            ("h", HIERARCHY),
        ]
        key = "".join(f"\x01{name}\x02{value}" for name, value in fields)
        lines.append(f"C '{key}' {count}")
    return "\n".join(lines) + "\n"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_coverage_cfg() -> dict:
    return {
        "backend": "verilator_coverage",
        "parser": "verilator",
        "merged_name": "merged.dat",
        "fail_under": 60.0,
        "report_cmd": ["echo", "report-stub"],
    }


def make_flow(root: Path) -> Dut:
    return Dut(
        name=DUT,
        kind="sim",
        description="coverage closure fixture",
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


def make_args() -> Namespace:
    return Namespace(
        dry_run=False,
        verbose=False,
        timeout=None,
        fail_under=None,
        quiet=True,
        _simulators={TOOL: {"supports_cov": SUPPORTED_METRICS}},
    )


def leaf_rel(run_rel: str) -> str:
    return f"{run_rel}/{ITEM}/seed_1/attempt_0"


def write_manifest(run_dir: Path, root: Path) -> None:
    """Write the merge manifest the `cov_merge` stage leaves for the report stage."""
    run_rel = run_dir.relative_to(root).as_posix()
    manifest = {
        "schema_version": 2,
        "dut": DUT,
        "tool": TOOL,
        "tool_version": TOOL_VERSION,
        "backend": "verilator_coverage",
        "parser": "verilator",
        "target": "default",
        "build_fingerprint": BUILD_FINGERPRINT,
        "supported_metrics": SUPPORTED_METRICS,
        "generated_at": MANIFEST_GENERATED_AT,
        "status": "PASS",
        "merge_return_code": 0,
        "selection_policy": "final_non_debug_attempt_per_test_seed",
        "selection_source": "result_json",
        "inputs": [
            {
                "attempt": 0,
                "build_fingerprint": BUILD_FINGERPRINT,
                "item": ITEM,
                "path": f"{leaf_rel(run_rel)}/coverage/coverage.dat",
                "result_json": f"{leaf_rel(run_rel)}/result.json",
                "seed": 1,
                "source": "result_json",
                "status": "PASS",
                "target": "default",
            }
        ],
        "rejected": [],
        "exclusions": [],
        "waivers": [],
        "artifacts": {"merged": f"{run_rel}/cov/merged.dat", "report": None, "summary": None},
        "policy": {
            "path": POLICY_REL.as_posix(),
            "sha256": sha256_of(root / POLICY_REL),
            "scope_epoch": "fixture-v1",
            "legacy_exclusions": [],
            "legacy_waivers": [],
            "native_files": [
                {
                    "apply_phase": "report",
                    "path": NATIVE_REL.as_posix(),
                    "role": "reference",
                    "sha256": sha256_of(root / NATIVE_REL),
                    "tool": TOOL,
                }
            ],
        },
    }
    write_json(run_dir / "cov" / "coverage.json", manifest)


def stage_fixture(root: Path, run_rel: str = "run") -> Path:
    """Build the merge-phase inputs of a coverage run at `root/run_rel` and the DUT policy
    under `root`: the policy files, the merged database, the lcov report, and the manifest."""
    (root / POLICY_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / POLICY_REL).write_text(POLICY_TOML, encoding="utf-8")
    (root / NATIVE_REL).write_text("", encoding="utf-8")
    run_dir = root / run_rel
    (run_dir / "cov" / "report").mkdir(parents=True)
    (run_dir / "cov" / "merged.dat").write_text(coverage_dat(), encoding="utf-8")
    (run_dir / "cov" / "report" / "coverage.info").write_text(LCOV_INFO, encoding="utf-8")
    write_manifest(run_dir, root)
    return run_dir


def drive_report_stage(root: Path, run_dir: Path) -> int:
    """Run the report phase of `coverage_stage` on the run staged at `run_dir`."""
    stage_dir = run_dir / "stages" / "cov_report"
    with mock.patch("runlib.stages._coverage_tool_version", return_value=TOOL_VERSION):
        return coverage_stage(
            make_flow(root),
            root,
            {"coverage": {TOOL: tool_coverage_cfg()}},
            TOOL,
            run_dir,
            "report",
            make_args(),
            stage_dir / "logs" / "cov_report.log",
            stage_dir / "scripts" / "cov_report.sh",
            stage_dir / "env" / "cov_report.env",
            True,
        )


def _recorded_stage(
    name: str,
    started: str,
    ended: str,
    *,
    run_rel: str,
    item: str | None = None,
    artifacts: dict | None = None,
    metadata: dict | None = None,
    reason: str = "process completed successfully",
    target: str | None = "default",
) -> StageResult:
    stage_rel = leaf_rel(run_rel) if item else f"{run_rel}/stages/{name}"
    log_name = f"{item}.log" if item else f"{name}.log"
    return StageResult(
        stage=name,
        item=item,
        status="PASS",
        return_code=0,
        duration_sec=12.345,
        started_at=f"2026-09-01T{started}.000000+00:00",
        ended_at=f"2026-09-01T{ended}.000000+00:00",
        log=f"{stage_rel}/logs/{log_name}",
        artifacts={
            "env": f"{stage_rel}/env/{name}.env",
            "script": f"{stage_rel}/scripts/{name}{'.' + item if item else ''}.sh",
            **(artifacts or {}),
        },
        failure_buckets=[],
        reason=reason,
        parser=None,
        metadata={"target": "default", **(metadata or {})} if target else dict(metadata or {}),
        target=target,
    )


def _recorded_stages(run_rel: str) -> list[StageResult]:
    """The passing stages that precede `cov_report` in a `--cov --regress` run."""
    leaf = leaf_rel(run_rel)
    coverage_meta = {
        "backend": "verilator_coverage",
        "build_fingerprint": BUILD_FINGERPRINT,
        "parser": "verilator",
        "supported_metrics": SUPPORTED_METRICS,
        "target": "default",
        "tool_version": TOOL_VERSION,
    }
    regress = _recorded_stage(
        "regress",
        "07:57:30",
        "07:59:00",
        run_rel=run_rel,
        item=ITEM,
        artifacts={
            "coverage": f"{leaf}/coverage/coverage.dat",
            "results_xml": f"{leaf}/results/results.xml",
        },
        metadata={
            "attempt": 0,
            "coverage": {
                "build_fingerprint": BUILD_FINGERPRINT,
                "debug_only": False,
                "path": f"{leaf}/coverage/coverage.dat",
                "requested": True,
                "supported_metrics": SUPPORTED_METRICS,
                "target": "default",
                "tool": TOOL,
            },
            "debug_only": False,
            "seed": 1,
        },
        reason="1 testcase(s) passed",
    )
    return [
        _recorded_stage("flist", "07:55:00", "07:55:01", run_rel=run_rel),
        _recorded_stage("hdl_compile", "07:55:01", "07:57:30", run_rel=run_rel),
        regress,
        _recorded_stage(
            "cov_merge",
            "07:59:00",
            "07:59:01",
            run_rel=run_rel,
            artifacts={
                "coverage": f"{run_rel}/cov/merged.dat",
                "coverage_inputs": [f"{leaf}/coverage/coverage.dat"],
                "coverage_manifest": f"{run_rel}/cov/coverage.json",
            },
            metadata={"coverage": coverage_meta},
            target=None,
        ),
    ]


def _regress_job(regress: StageResult, run_rel: str) -> dict:
    """The scheduler job record of the one regression leaf."""
    return {
        "stage": "regress",
        "item": ITEM,
        "target": "default",
        "seed": 1,
        "attempt": 0,
        "status": regress.status,
        "return_code": regress.return_code,
        "reason": regress.reason,
        "duration_sec": regress.duration_sec,
        "started_at": regress.started_at,
        "ended_at": regress.ended_at,
        "log": regress.log,
        "artifacts": regress.artifacts,
        "failure_buckets": [],
        "parser": None,
        "metadata": regress.metadata,
        "result_json": f"{leaf_rel(run_rel)}/result.json",
    }


def finish_run(root: Path, run_rel: str = "run") -> Path:
    """Stage the run, grade it through the runner's `cov_report` stage, and write the run-level
    `result.json` and `regression.json` as the runner does at the end of a `--cov --regress`
    run. The graded report fails its toggle threshold."""
    run_dir = stage_fixture(root, run_rel)
    stages = _recorded_stages(run_rel)
    flow = dataclasses.replace(
        make_flow(root), raw={"native": {"stages": {"cov_report": {"kind": "coverage_report"}}}}
    )
    args = Namespace(
        cov=True,
        dut=DUT,
        items=[ITEM],
        regress=True,
        run_dir=run_rel,
        tool=TOOL,
        ui="plain",
        dry_run=False,
        verbose=False,
        quiet=True,
        timeout=None,
        fail_under=None,
        seed=None,
        sim_jobs=1,
        waves=None,
    )
    with (
        mock.patch("runlib.stages._coverage_tool_version", return_value=TOOL_VERSION),
        redirect_stdout(io.StringIO()),
    ):
        report = run_stage(
            flow,
            root,
            {"coverage": {TOOL: tool_coverage_cfg()}},
            TestCatalog(path=None, tests={}, groups={}),
            "cov_report",
            None,
            args,
            TOOL,
            run_dir,
            {TOOL: {"supports_cov": SUPPORTED_METRICS}},
            {},
        )
    stages.append(report)
    versions = {"bender": "bender 0.32.1", "python": "3.11.15", TOOL: TOOL_VERSION}
    git = {"branch": "main", "commit": "0" * 40, "dirty": "false"}
    common = dict(flow=flow, root=root, tool=TOOL, run_dir=run_dir, stages=stages, args=args)
    write_result(
        run_dir / "result.json",
        result_payload(
            dry_run=False, items=[ITEM], label=ITEM, versions=versions, git_metadata=git, **common
        ),
    )
    write_result(
        run_dir / REGRESSION_REL,
        regression_payload(
            jobs=[_regress_job(stages[2], run_rel)],
            items=[ITEM],
            elapsed_sec=245.0,
            versions=versions,
            git_metadata=git,
            **common,
        ),
    )
    return run_dir


def grade_run(
    root: Path,
    run_dir: Path,
    *,
    threshold: float = 60.0,
    tool_version: str = TOOL_VERSION,
    supported_metrics: list[str] | None = None,
) -> tuple[dict, CoverageGrade]:
    """Parse and grade `run_dir` directly, writing the raw details after the grade.

    Returns the raw details payload and the grade.
    """
    paths = coverage_run_paths(run_dir, "merged.dat")
    manifest = load_manifest(paths.manifest)
    policy = load_coverage_policy(root / POLICY_REL, expected_dut=DUT)
    parsed = parse_coverage_run(
        parser="verilator",
        dut=DUT,
        tool=TOOL,
        manifest=manifest,
        merged=paths.merged,
        report_dir=paths.report_dir,
        log_path=None,
    )
    raw = parsed.details.to_dict()
    grade = grade_coverage_run(
        parsed=parsed,
        manifest=manifest,
        dut=DUT,
        root=root,
        tool=TOOL,
        tool_cov=tool_coverage_cfg(),
        run_dir=run_dir,
        policy=policy,
        threshold=threshold,
        tool_version=tool_version,
        supported_metrics=SUPPORTED_METRICS if supported_metrics is None else supported_metrics,
    )
    write_json(paths.raw_details, raw)
    return raw, grade


def json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def assert_artifacts_exist(self, artifacts: dict, where: str) -> None:
        for key, value in artifacts.items():
            with self.subTest(file=where, artifact=key):
                self.assertIsInstance(value, str)
                self.assertTrue((self.root / value).exists(), f"{where} {key}={value!r}")

    def assert_expected_grade(self, summary: dict, application: dict) -> None:
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["threshold"], 60.0)
        self.assertFalse(summary["threshold_met"])
        self.assertEqual(summary["overall_percent"], EXPECTED_OVERALL)
        self.assertEqual(summary["metrics"], EXPECTED_METRICS)
        self.assertEqual(
            [outcome["met"] for outcome in summary["policy_thresholds"]], EXPECTED_THRESHOLDS_MET
        )
        holes = summary["holes_summary"]
        self.assertEqual({key: holes[key] for key in EXPECTED_HOLES}, EXPECTED_HOLES)
        self.assertEqual([m["policy_id"] for m in application["matched"]], EXPECTED_MATCHED)
        self.assertEqual(application["warnings"], [])


class ReportStage(FixtureCase):
    def test_report_phase_writes_every_graded_file_and_fails_the_threshold(self):
        run_dir = stage_fixture(self.root)
        self.assertEqual(drive_report_stage(self.root, run_dir), 1)
        for name, rel in GRADED_FILES.items():
            with self.subTest(file=name):
                self.assertTrue((self.root / rel).is_file())
        report = run_dir / "cov" / "report"
        self.assert_expected_grade(
            read_json(report / "summary.json"), read_json(report / "policy-application.json")
        )
        log = (self.root / GRADED_FILES["cov_report.log"]).read_text(encoding="utf-8")
        self.assertIn("# COVERAGE THRESHOLD: 57.1429 < 60.0", log)
        self.assertIn(
            "# COVERAGE THRESHOLD: toggle-effective metric=toggle actual=60.0 minimum=90.0 "
            "unclassified=1",
            log,
        )
        manifest = read_json(run_dir / "cov" / "coverage.json")
        self.assertEqual(manifest["status"], "FAIL")
        self.assertEqual(manifest["generated_at"], MANIFEST_GENERATED_AT)
        self.assertEqual(manifest["artifacts"]["summary"], "run/cov/report/summary.json")
        summary_holes = read_json(report / "summary.json")["holes_summary"]
        self.assertIn("samples", summary_holes)
        self.assertEqual(
            manifest["holes_summary"],
            {k: v for k, v in summary_holes.items() if k not in ("samples", "sample_truncated")},
        )

    def test_report_phase_reads_the_merged_database_from_the_run_dir(self):
        run_dir = stage_fixture(self.root, "elsewhere/run")
        self.assertFalse((self.root / "run").exists())
        self.assertEqual(drive_report_stage(self.root, run_dir), 1)
        manifest = read_json(run_dir / "cov" / "coverage.json")
        self.assertEqual(manifest["artifacts"]["merged"], "elsewhere/run/cov/merged.dat")
        self.assert_artifacts_exist(manifest["artifacts"], "coverage.json")


class GradeCoverageRun(FixtureCase):
    def test_direct_grade_writes_what_the_report_stage_writes(self):
        staged_root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, staged_root, ignore_errors=True)
        self.assertEqual(drive_report_stage(staged_root, stage_fixture(staged_root)), 1)
        run_dir = stage_fixture(self.root)
        raw, grade = grade_run(self.root, run_dir)
        self.assertEqual(grade.status, "FAIL")
        self.assertFalse(grade.compatibility_threshold_met)
        self.assertEqual([o["met"] for o in grade.thresholds], EXPECTED_THRESHOLDS_MET)
        self.assertEqual(
            json_bytes(raw), (staged_root / GRADED_FILES["coverage-details.raw.json"]).read_bytes()
        )
        for name in GRADE_WRITES:
            with self.subTest(file=name):
                self.assertEqual(
                    (self.root / GRADED_FILES[name]).read_bytes(),
                    (staged_root / GRADED_FILES[name]).read_bytes(),
                )
        self.assertFalse((self.root / GRADED_FILES["cov_report.log"]).exists())

    def test_policy_rejection_writes_none_of_the_graded_files(self):
        run_dir = stage_fixture(self.root)
        policy_path = self.root / POLICY_REL
        policy_path.write_text(
            policy_path.read_text(encoding="utf-8").replace(
                'native_locator = "*|o=scan_ctrl_i.capture_en:0->1|*"',
                'native_locator = "*|o=scan_ctrl_i.no_such_signal:0->1|*"',
            ),
            encoding="utf-8",
        )
        manifest_before = (run_dir / "cov" / "coverage.json").read_bytes()
        with self.assertRaises(ConfigError):
            grade_run(self.root, run_dir)
        for name in REPORT_FILES:
            with self.subTest(file=name):
                self.assertFalse((self.root / GRADED_FILES[name]).exists())
        self.assertEqual((run_dir / "cov" / "coverage.json").read_bytes(), manifest_before)

    def test_relocated_run_grades_from_its_own_tree(self):
        run_dir = stage_fixture(self.root, "elsewhere/run")
        _raw, grade = grade_run(self.root, run_dir)
        self.assertEqual(grade.status, "FAIL")
        summary = read_json(run_dir / "cov" / "report" / "summary.json")
        manifest = read_json(run_dir / "cov" / "coverage.json")
        self.assertEqual(summary["artifacts"]["merged"], "elsewhere/run/cov/merged.dat")
        self.assertEqual(manifest["artifacts"]["merged"], "elsewhere/run/cov/merged.dat")
        self.assert_artifacts_exist(summary["artifacts"], "summary.json")
        self.assert_artifacts_exist(manifest["artifacts"], "coverage.json")

    def test_host_values_are_written_as_given(self):
        run_dir = stage_fixture(self.root)
        _raw, grade = grade_run(
            self.root,
            run_dir,
            threshold=42.5,
            tool_version="carried-version",
            supported_metrics=["line"],
        )
        self.assertEqual(grade.threshold, 42.5)
        self.assertTrue(grade.compatibility_threshold_met)
        summary = read_json(run_dir / "cov" / "report" / "summary.json")
        manifest = read_json(run_dir / "cov" / "coverage.json")
        self.assertEqual(summary["threshold"], 42.5)
        self.assertEqual(summary["tool_versions"], {TOOL: "carried-version"})
        self.assertEqual(summary["supported_metrics"], ["line"])
        self.assertEqual(manifest["threshold"], 42.5)
        self.assertEqual(manifest["tool_version"], TOOL_VERSION)
        self.assertEqual(manifest["supported_metrics"], SUPPORTED_METRICS)


class FinishedRun(FixtureCase):
    def test_finish_run_records_a_threshold_failure_the_runner_way(self):
        run_dir = finish_run(self.root)
        result = read_json(run_dir / "result.json")
        self.assertEqual((result["status"], result["exit_code"]), ("FAIL", 1))
        self.assertEqual(
            [(s["name"], s["status"]) for s in result["stages"]],
            [
                ("flist", "PASS"),
                ("hdl_compile", "PASS"),
                ("regress", "PASS"),
                ("cov_merge", "PASS"),
                ("cov_report", "FAIL"),
            ],
        )
        record = result["stages"][-1]
        self.assertEqual(record["reason"], "coverage threshold not met")
        self.assertEqual(record["failure_buckets"][0]["kind"], "coverage_threshold")
        self.assertEqual(record["log"], GRADED_FILES["cov_report.log"].as_posix())
        self.assert_artifacts_exist(
            {k: v for k, v in record["artifacts"].items() if k != "coverage_inputs"},
            "cov_report record",
        )
        self.assertFalse(result["coverage"]["threshold_met"])
        self.assertEqual(result["coverage"]["holes_summary"]["open"], EXPECTED_HOLES["open"])
        self.assertNotIn("samples", result["coverage"]["holes_summary"])
        self.assertEqual(result["tests"]["total"], 1)
        regression = read_json(run_dir / REGRESSION_REL)
        self.assertEqual((regression["status"], regression["exit_code"]), ("FAIL", 1))
        self.assertEqual(len(regression["jobs"]), 1)
        self.assertEqual(regression["artifacts"]["coverage_summary"], "run/cov/report/summary.json")


if __name__ == "__main__":
    unittest.main()
