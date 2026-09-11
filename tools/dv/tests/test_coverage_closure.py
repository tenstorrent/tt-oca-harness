# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Tests for the post-report coverage grading shared by the report stage.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
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
from runlib.models import ConfigError, Dut  # noqa: E402
from runlib.stages import coverage_stage  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "coverage_closure"
GOLDEN = FIXTURE / "golden"
TOOL = "verilator"
DUT = "fixture"
TOOL_VERSION = "Verilator 5.050 2026-07-01 rev vUNKNOWN-built20260701"
SUPPORTED_METRICS = ["line", "toggle", "branch"]
POLICY_REL = Path("dut/cov/config/verilator/coverage_policy.toml")
# Golden file name -> path under the staged root; the report stage writes each of these.
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


def stage_fixture(root: Path, run_rel: str = "run") -> Path:
    """Copy the fixture run tree to `root/run_rel` and the DUT policy under `root`."""
    run_dir = root / run_rel
    shutil.copytree(FIXTURE / "run", run_dir)
    shutil.copytree(FIXTURE / "dut", root / "dut")
    return run_dir


def drive_report_stage(root: Path, run_dir: Path) -> int:
    """Run the report phase of `coverage_stage` on the fixture staged at `run_dir`."""
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


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def assert_artifacts_exist(self, artifacts: dict, where: str) -> None:
        for key, value in artifacts.items():
            with self.subTest(file=where, artifact=key):
                self.assertIsInstance(value, str)
                self.assertTrue((self.root / value).exists(), f"{where} {key}={value!r}")


class ReportStageGolden(FixtureCase):
    def test_report_phase_reproduces_the_golden_files(self):
        run_dir = stage_fixture(self.root)
        self.assertEqual(drive_report_stage(self.root, run_dir), 1)
        for name, rel in GRADED_FILES.items():
            with self.subTest(file=name):
                self.assertEqual((self.root / rel).read_bytes(), (GOLDEN / name).read_bytes())

    def test_report_phase_reads_the_merged_database_from_the_run_dir(self):
        run_dir = stage_fixture(self.root, "elsewhere/run")
        self.assertFalse((self.root / "run").exists())
        self.assertEqual(drive_report_stage(self.root, run_dir), 1)
        manifest = json.loads((run_dir / "cov" / "coverage.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["artifacts"]["merged"], "elsewhere/run/cov/merged.dat")
        self.assert_artifacts_exist(manifest["artifacts"], "coverage.json")


class GradeCoverageRun(FixtureCase):
    def test_direct_grade_matches_the_stage_golden(self):
        run_dir = stage_fixture(self.root)
        raw, grade = grade_run(self.root, run_dir)
        self.assertEqual(grade.status, "FAIL")
        self.assertFalse(grade.compatibility_threshold_met)
        self.assertEqual([o["met"] for o in grade.thresholds], [True, False])
        self.assertEqual(json_bytes(raw), (GOLDEN / "coverage-details.raw.json").read_bytes())
        for name in GRADE_WRITES:
            with self.subTest(file=name):
                self.assertEqual(
                    (self.root / GRADED_FILES[name]).read_bytes(), (GOLDEN / name).read_bytes()
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
        summary = json.loads((run_dir / "cov" / "report" / "summary.json").read_text("utf-8"))
        manifest = json.loads((run_dir / "cov" / "coverage.json").read_text("utf-8"))
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
        summary = json.loads((run_dir / "cov" / "report" / "summary.json").read_text("utf-8"))
        manifest = json.loads((run_dir / "cov" / "coverage.json").read_text("utf-8"))
        self.assertEqual(summary["threshold"], 42.5)
        self.assertEqual(summary["tool_versions"], {TOOL: "carried-version"})
        self.assertEqual(summary["supported_metrics"], ["line"])
        self.assertEqual(manifest["threshold"], 42.5)
        self.assertEqual(manifest["tool_version"], TOOL_VERSION)
        self.assertEqual(manifest["supported_metrics"], SUPPORTED_METRICS)


if __name__ == "__main__":
    unittest.main()
