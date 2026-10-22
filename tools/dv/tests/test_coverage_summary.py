# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the URG report table a coverage grade reads.

The `Total Coverage Summary` follows the design hierarchy; the `Total Module Definition
Coverage Summary` counts each version of a module once. A run records the table it grades
as `graded_summary` in coverage.json, and the report stage's `--cov-summary` replaces it.

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

from runlib.coverage import (  # noqa: E402
    CoverageReportError,
    parse_coverage_report,
    parse_urg_summary_table,
    write_json,
)
from runlib.coverage_parsers.urg import parse_urg_details  # noqa: E402
from runlib.models import ConfigError, Dut  # noqa: E402
from runlib.stages import coverage_stage  # noqa: E402

DUT = "fixture"
TOOL = "vcs"

HIERARCHY = (
    "Total Coverage Summary \n"
    "SCORE  LINE   COND   TOGGLE FSM    BRANCH GROUP  \n"
    " 59.32  82.84  67.74  54.17  30.61  73.68  46.88 \n\n"
)
MODULE_DEFINITION = (
    "Total Module Definition Coverage Summary \n"
    "SCORE  LINE   COND   TOGGLE FSM    BRANCH \n"
    " 62.77  83.13  73.56  48.27  30.61  78.28 \n\n"
)
DASHBOARD = "Dashboard\n\n" + HIERARCHY + MODULE_DEFINITION
# Stand-in for `urg -report DIR`: copies the dashboard named by its second argument.
REPORT_STUB = (
    "import pathlib, shutil, sys\n"
    "out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)\n"
    "shutil.copy(sys.argv[2], out / 'dashboard.txt')\n"
)


class SummaryTables(unittest.TestCase):
    def test_each_table_parses_and_the_module_table_borrows_the_group_column(self):
        self.assertEqual(
            parse_urg_summary_table(DASHBOARD),
            {
                "score": 59.32,
                "line": 82.84,
                "cond": 67.74,
                "toggle": 54.17,
                "fsm": 30.61,
                "branch": 73.68,
                "group": 46.88,
            },
        )
        # Its score is the mean of its columns, the group column included.
        self.assertEqual(
            parse_urg_summary_table(DASHBOARD, "module_definition"),
            {
                "score": 60.12,
                "line": 83.13,
                "cond": 73.56,
                "toggle": 48.27,
                "fsm": 30.61,
                "branch": 78.28,
                "group": 46.88,
            },
        )
        self.assertEqual(parse_urg_summary_table(HIERARCHY, "module_definition"), {})


class GradedSummary(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-summary-"))
        self.report = self.root / "report"
        self.report.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, text: str) -> None:
        (self.report / "dashboard.txt").write_text(text)
        (self.report / "modinfo.txt").write_text("uncovered line rtl/top.sv:12\n")

    def details(self, summary: str):
        return parse_urg_details(
            dut=DUT,
            tool=TOOL,
            target="default",
            build_fingerprint="fp",
            report_dir=self.report,
            log_path=None,
            summary=summary,
        )

    def test_the_scalar_report_reads_the_named_table(self):
        self.write(DASHBOARD)
        merged = self.root / "merged.vdb"
        metrics, overall = parse_coverage_report(
            parser="urg", report_dir=self.report, merged=merged, summary="module_definition"
        )
        self.assertEqual((metrics["line"], metrics["toggle"], overall), (83.13, 48.27, 60.12))
        metrics, overall = parse_coverage_report(
            parser="urg", report_dir=self.report, merged=merged
        )
        self.assertEqual((metrics["line"], overall), (82.84, 59.32))

    def test_a_report_without_the_module_table_is_an_error(self):
        self.write("Dashboard\n\n" + HIERARCHY)
        with self.assertRaisesRegex(CoverageReportError, "no `Total Module Definition"):
            parse_coverage_report(
                parser="urg",
                report_dir=self.report,
                merged=self.root / "merged.vdb",
                summary="module_definition",
            )

    def test_the_module_table_is_another_grade_of_the_same_report(self):
        self.write(DASHBOARD)
        hierarchy = self.details("hierarchy")
        module = self.details("module_definition")
        by_family = {record.metric_family: record.effective_percent for record in module.metrics}
        self.assertEqual((by_family["line"], by_family["toggle"]), (83.13, 48.27))
        self.assertNotEqual(hierarchy.scope_fingerprint, module.scope_fingerprint)


def make_flow(root: Path) -> Dut:
    return Dut(
        name=DUT,
        kind="sim",
        description="graded summary fixture",
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


class ReportStageSummary(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-summary-stage-"))
        self.run_dir = self.root / "run"
        (self.run_dir / "cov" / "merged.vdb").mkdir(parents=True)
        (self.run_dir / "cov" / "merged.vdb" / "db").write_text("x")
        self.dashboard = self.root / "dashboard.txt"
        self.dashboard.write_text(DASHBOARD)
        self.write_manifest()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write_manifest(self, **extra) -> None:
        write_json(
            self.run_dir / "cov" / "coverage.json",
            {
                "schema_version": 2,
                "dut": DUT,
                "tool": TOOL,
                "parser": "urg",
                "backend": "urg",
                "status": "PASS",
                "target": "default",
                "build_fingerprint": "fp",
                "supported_metrics": ["line", "cond", "toggle"],
                "inputs": [],
                "artifacts": {"merged": "run/cov/merged.vdb"},
                **extra,
            },
        )

    def report(self, cov_summary: str | None = None, parser: str = "urg") -> int:
        stage_dir = self.run_dir / "stages" / "cov_report"
        tool_cov = {
            "backend": "urg",
            "parser": parser,
            "merged_name": "merged.vdb",
            "report_cmd": [sys.executable, "-c", REPORT_STUB, "{report}", str(self.dashboard)],
        }
        args = Namespace(
            dry_run=False,
            verbose=False,
            timeout=None,
            fail_under=None,
            cov_summary=cov_summary,
            quiet=True,
            rebuild=False,
            cov=True,
            _simulators={TOOL: {"supports_cov": ["line", "cond", "toggle"]}},
        )
        with mock.patch("runlib.stages._coverage_tool_version", return_value="vcs X"):
            return coverage_stage(
                make_flow(self.root),
                self.root,
                {"coverage": {TOOL: tool_cov}},
                TOOL,
                self.run_dir,
                "report",
                args,
                stage_dir / "logs" / "cov_report.log",
                stage_dir / "scripts" / "cov_report.sh",
                stage_dir / "env" / "cov_report.env",
                True,
            )

    def graded(self) -> tuple[str | None, float]:
        manifest = json.loads((self.run_dir / "cov" / "coverage.json").read_text())
        details = json.loads(
            (self.run_dir / "cov" / "report" / "coverage-details.json").read_text()
        )
        line = next(m for m in details["metrics"] if m["metric_family"] == "line")
        return manifest.get("graded_summary"), line["effective_percent"]

    def test_the_report_grades_the_table_the_merge_recorded(self):
        self.write_manifest(graded_summary="module_definition")
        self.assertEqual(self.report(), 0)
        self.assertEqual(self.graded(), ("module_definition", 83.13))

    def test_cov_summary_replaces_the_recorded_table(self):
        self.assertEqual(self.report("module_definition"), 0)
        self.assertEqual(self.graded(), ("module_definition", 83.13))
        self.assertEqual(self.report("hierarchy"), 0)
        self.assertEqual(self.graded(), (None, 82.84))

    def test_only_a_urg_report_has_a_module_table(self):
        with self.assertRaisesRegex(ConfigError, "coverage.vcs.parser is `imc`"):
            self.report("module_definition", parser="imc")


if __name__ == "__main__":
    unittest.main()
