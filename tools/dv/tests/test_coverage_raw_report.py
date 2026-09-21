# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the raw and effective figures of a URG-graded report.

URG applies an exclusion file while it reports, so one report carries either figure. The
report stage runs the report command a second time without its exclusion inputs, and the
parser takes each family's raw percentage from that report.

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

from runlib.coverage import write_json  # noqa: E402
from runlib.coverage_parsers.urg import parse_urg_details  # noqa: E402
from runlib.models import Dut  # noqa: E402
from runlib.stages import coverage_stage  # noqa: E402

DUT = "fixture"
TOOL = "vcs"


def dashboard(line: float, cond: float, toggle: float) -> str:
    return (
        "Dashboard\n\nTotal Coverage Summary \n"
        "SCORE  LINE   COND   TOGGLE FSM    BRANCH ASSERT GROUP  \n"
        f" 80.00  {line:.2f}  {cond:.2f}  {toggle:.2f}  50.00  85.00  95.00 100.00 \n\n"
    )


# Stand-in for `urg -report DIR [...]`: extra arguments are the exclusion inputs the report
# stage appends, so their presence selects the lower (effective) figures.
REPORT_STUB = (
    "import pathlib, sys\n"
    "out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)\n"
    "excluded = len(sys.argv) > 2\n"
    "line, cond, tgl = (90.0, 80.0, 60.0) if excluded else (95.0, 85.0, 70.0)\n"
    "(out / 'dashboard.txt').write_text(\n"
    "    'Total Coverage Summary \\n'\n"
    "    'SCORE  LINE   COND   TOGGLE FSM    BRANCH ASSERT GROUP  \\n'\n"
    "    f' 80.00  {line:.2f}  {cond:.2f}  {tgl:.2f}  50.00  85.00  95.00 100.00 \\n'\n"
    ")\n"
)


def make_flow(root: Path) -> Dut:
    return Dut(
        name=DUT,
        kind="sim",
        description="raw report fixture",
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
        rebuild=False,
        cov=True,
        _simulators={TOOL: {"supports_cov": ["line", "cond", "toggle"]}},
    )


class UrgParserRawReport(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-raw-report-"))
        self.report = self.root / "report"
        self.report.mkdir()
        (self.report / "dashboard.txt").write_text(dashboard(90.0, 80.0, 60.0))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def parse(self, raw_report_dir=None):
        return parse_urg_details(
            dut=DUT,
            tool=TOOL,
            target="default",
            build_fingerprint="fp",
            report_dir=self.report,
            log_path=None,
            raw_report_dir=raw_report_dir,
        )

    def test_without_a_raw_report_both_figures_are_the_reported_one(self):
        details = self.parse()
        by_family = {record.metric_family: record for record in details.metrics}
        self.assertEqual(
            (by_family["line"].raw_percent, by_family["line"].effective_percent), (90.0, 90.0)
        )

    def test_raw_report_supplies_the_raw_figure_per_family(self):
        raw = self.root / "report_raw"
        raw.mkdir()
        (raw / "dashboard.txt").write_text(dashboard(95.0, 85.0, 70.0))
        details = self.parse(raw)
        by_family = {record.metric_family: record for record in details.metrics}
        self.assertEqual(
            (by_family["line"].raw_percent, by_family["line"].effective_percent), (95.0, 90.0)
        )
        self.assertEqual(
            (by_family["toggle"].raw_percent, by_family["toggle"].effective_percent), (70.0, 60.0)
        )
        self.assertEqual(by_family["branch"].raw_percent, by_family["branch"].effective_percent)
        self.assertFalse([w for w in details.warnings if "raw URG" in w])

    def test_empty_raw_report_is_a_warning_not_a_figure(self):
        raw = self.root / "report_raw"
        raw.mkdir()
        details = self.parse(raw)
        by_family = {record.metric_family: record for record in details.metrics}
        self.assertEqual(by_family["line"].raw_percent, 90.0)
        self.assertTrue(any("raw URG report files were not found" in w for w in details.warnings))


class ReportStageRawPass(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-raw-stage-"))
        self.run_dir = self.root / "run"
        (self.run_dir / "cov" / "merged.vdb").mkdir(parents=True)
        (self.run_dir / "cov" / "merged.vdb" / "db").write_text("x")
        (self.root / "dut" / "cov" / "config" / "vcs").mkdir(parents=True)
        self.exclusions = self.root / "dut" / "cov" / "config" / "vcs" / "unreachable.el"
        self.exclusions.write_text("# exclusion list\n")
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
            },
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def tool_cov(self, exclude: bool) -> dict:
        cfg = {
            "backend": "urg",
            "parser": "urg",
            "merged_name": "merged.vdb",
            "report_cmd": [sys.executable, "-c", REPORT_STUB, "{report}"],
        }
        if exclude:
            cfg["exclude_files"] = ["dut/cov/config/vcs/unreachable.el"]
        return cfg

    def report(self, exclude: bool) -> int:
        stage_dir = self.run_dir / "stages" / "cov_report"
        with mock.patch("runlib.stages._coverage_tool_version", return_value="vcs X"):
            return coverage_stage(
                make_flow(self.root),
                self.root,
                {"coverage": {TOOL: self.tool_cov(exclude)}},
                TOOL,
                self.run_dir,
                "report",
                make_args(),
                stage_dir / "logs" / "cov_report.log",
                stage_dir / "scripts" / "cov_report.sh",
                stage_dir / "env" / "cov_report.env",
                True,
            )

    def test_exclusions_produce_a_raw_report_and_distinct_figures(self):
        self.assertEqual(self.report(exclude=True), 0)
        raw_dir = self.run_dir / "cov" / "report_raw"
        self.assertTrue((raw_dir / "dashboard.txt").is_file())
        stage_dir = self.run_dir / "stages" / "cov_report"
        self.assertTrue((stage_dir / "logs" / "cov_report.raw.log").is_file())
        self.assertTrue((stage_dir / "scripts" / "cov_report.raw.sh").is_file())
        details = json.loads(
            (self.run_dir / "cov" / "report" / "coverage-details.json").read_text()
        )
        line = next(m for m in details["metrics"] if m["metric_family"] == "line")
        self.assertEqual((line["raw_percent"], line["effective_percent"]), (95.0, 90.0))
        summary = json.loads((self.run_dir / "cov" / "report" / "summary.json").read_text())
        self.assertNotIn("raw_metrics", summary)
        self.assertNotIn("report_raw", summary["artifacts"])
        manifest = json.loads((self.run_dir / "cov" / "coverage.json").read_text())
        self.assertEqual(manifest["artifacts"]["report_raw"], "run/cov/report_raw")
        log = (stage_dir / "logs" / "cov_report.log").read_text()
        self.assertIn("# COVERAGE FAMILY: line raw=95.00 effective=90.00", log)
        self.assertIn("# COVERAGE FAMILY: toggle raw=70.00 effective=60.00", log)

    def test_without_exclusions_one_report_is_both_and_a_stale_raw_report_goes(self):
        stale = self.run_dir / "cov" / "report_raw"
        stale.mkdir(parents=True)
        (stale / "dashboard.txt").write_text(dashboard(1.0, 1.0, 1.0))
        self.assertEqual(self.report(exclude=False), 0)
        self.assertFalse(stale.exists())
        details = json.loads(
            (self.run_dir / "cov" / "report" / "coverage-details.json").read_text()
        )
        line = next(m for m in details["metrics"] if m["metric_family"] == "line")
        self.assertEqual(line["raw_percent"], line["effective_percent"])
        manifest = json.loads((self.run_dir / "cov" / "coverage.json").read_text())
        self.assertNotIn("report_raw", manifest["artifacts"])


if __name__ == "__main__":
    unittest.main()
