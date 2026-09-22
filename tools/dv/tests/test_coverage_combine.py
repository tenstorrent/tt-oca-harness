# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for `--cov-combine`: finished runs as the inputs of one combined run.

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

from runlib.cli import parse_args, validate_combine_options  # noqa: E402
from runlib.coverage import write_json  # noqa: E402
from runlib.coverage_combine import plan_combine  # noqa: E402
from runlib.models import ConfigError, Dut  # noqa: E402
from runlib.stages import coverage_stage  # noqa: E402

DUT = "fixture"
TOOL = "vcs"
COMMIT = "fc7eb2c6a9a4ff3750f98b2e3ea37d080dd1eb82"

# Stand-in for `urg -flex_merge union -dir ... -dbname MERGED`: records its inputs in the
# merged database it creates.
MERGE_STUB = (
    "import pathlib, sys\n"
    "out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)\n"
    "(out / 'inputs.txt').write_text('\\n'.join(sys.argv[2:]) + '\\n')\n"
)


def make_flow(root: Path) -> Dut:
    return Dut(
        name=DUT,
        kind="sim",
        description="union fixture",
        framework="cocotb",
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root="dut",
        default_tool=TOOL,
        tools=[TOOL],
        path=root / "dut" / "fixture_sim_cfg.toml",
        raw={},
        frameworks=["cocotb", "uvm"],
        default_framework="cocotb",
    )


def make_args(plan) -> Namespace:
    return Namespace(
        dry_run=False,
        verbose=False,
        timeout=None,
        fail_under=None,
        quiet=True,
        rebuild=False,
        cov=True,
        _simulators={TOOL: {"supports_cov": ["line"]}},
        _cov_combine_plan=plan,
    )


def write_run(
    root: Path,
    name: str,
    *,
    framework: str,
    commit: str = COMMIT,
    tool: str = TOOL,
    completed: bool = True,
    cov_status: str = "PASS",
    design_db: bool = True,
    fingerprint: str = "fp-cocotb",
) -> Path:
    run_dir = root / "runs" / name
    (run_dir / "cov" / "merged.vdb").mkdir(parents=True)
    (run_dir / "cov" / "merged.vdb" / "db").write_text("x")
    artifacts = {"merged": f"runs/{name}/cov/merged.vdb"}
    if design_db:
        build = root / "build" / name / "cov_build.vdb"
        build.mkdir(parents=True)
        (build / "db").write_text("x")
        artifacts["design_db"] = f"build/{name}/cov_build.vdb"
    write_json(
        run_dir / "cov" / "coverage.json",
        {
            "schema_version": 2,
            "dut": DUT,
            "tool": tool,
            "parser": "urg",
            "backend": "urg",
            "status": cov_status,
            "merge_return_code": 0,
            "report_return_code": 2 if cov_status == "ERROR" else 0,
            "target": "default",
            "build_fingerprint": fingerprint,
            "tool_version": "vcs X",
            "supported_metrics": ["line"],
            "inputs": [{"path": f"runs/{name}/t/seed_1/attempt_0/coverage/simv.vdb"}] * 3,
            "artifacts": artifacts,
        },
    )
    write_json(
        run_dir / "result.json",
        {
            "schema_version": 1,
            "flow": DUT,
            "framework": framework,
            "tool": tool,
            "tool_version": "vcs X",
            "status": "PASS",
            "tests": {"completed": completed, "leaves_run": 3, "leaves_planned": 3},
            "git": {"commit": commit, "branch": "HEAD", "dirty": "false"},
        },
    )
    return run_dir


class PlanCombine(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-union-"))
        self.flow = make_flow(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_two_frameworks_of_one_commit_plan_as_one_combined_run(self):
        # A run graded FAIL against its own thresholds is a valid input: the combined run is
        # graded on its own.
        a = write_run(self.root, "a", framework="cocotb", cov_status="FAIL")
        b = write_run(self.root, "b", framework="uvm", fingerprint="fp-uvm")
        plan = plan_combine(self.root, self.flow, None, [Path("runs/a"), b])
        self.assertEqual(plan.tool, TOOL)
        self.assertEqual(plan.commit, COMMIT)
        self.assertEqual(plan.frameworks, ["cocotb", "uvm"])
        self.assertEqual(plan.target, "default")
        self.assertIsNone(plan.build_fingerprint)
        self.assertEqual(
            plan.input_paths(),
            [
                str(self.root / "build" / "a" / "cov_build.vdb"),
                str(self.root / "build" / "b" / "cov_build.vdb"),
                str(a / "cov" / "merged.vdb"),
                str(b / "cov" / "merged.vdb"),
            ],
        )
        discovery = plan.discovery(self.root)
        self.assertEqual([entry.item for entry in discovery.inputs], ["run:a", "run:b"])
        self.assertEqual({entry.source for entry in discovery.inputs}, {"run_dir"})
        self.assertEqual(discovery.selection_source, "run_dirs")
        payload = plan.manifest_payload(self.root)
        self.assertEqual([run["framework"] for run in payload["input_runs"]], ["cocotb", "uvm"])
        self.assertEqual(payload["input_runs"][0]["leaves"], 3)

    def test_refusals(self):
        write_run(self.root, "a", framework="cocotb")
        write_run(self.root, "b", framework="uvm")
        write_run(self.root, "other", framework="uvm", commit="0" * 40)
        write_run(self.root, "xcel", framework="cocotb", tool="xcelium")
        write_run(self.root, "partial", framework="cocotb", completed=False)
        write_run(self.root, "red", framework="cocotb", cov_status="ERROR")
        cases = {
            "one run": ([Path("runs/a")], "at least two"),
            "same run twice": ([Path("runs/a"), Path("runs/a")], "twice"),
            "commit mismatch": ([Path("runs/a"), Path("runs/other")], "different commits"),
            "tool mismatch": ([Path("runs/a"), Path("runs/xcel")], "different tools"),
            "incomplete run": ([Path("runs/a"), Path("runs/partial")], "only finished runs"),
            "failed coverage": ([Path("runs/a"), Path("runs/red")], "coverage status"),
            "missing run": ([Path("runs/a"), Path("runs/none")], "no result.json"),
        }
        for name, (dirs, text) in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ConfigError, text):
                    plan_combine(self.root, self.flow, None, dirs)
        with self.assertRaisesRegex(ConfigError, "does not match the runs' tool"):
            plan_combine(self.root, self.flow, "xcelium", [Path("runs/a"), Path("runs/b")])


class RunsFromAnotherCheckout(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-union-root-")).resolve()
        self.other = Path(tempfile.mkdtemp(prefix="ocah-union-other-")).resolve()
        self.flow = make_flow(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.other, ignore_errors=True)

    def test_artifacts_resolve_against_the_run_tree_that_produced_them(self):
        # Both runs were produced in `other`; their records name `runs/<name>` relative to
        # it, and run `b` has no design database.
        a = write_run(self.other, "a", framework="cocotb")
        b = write_run(self.other, "b", framework="uvm")
        for name in ("a", "b"):
            result_path = self.other / "runs" / name / "result.json"
            payload = json.loads(result_path.read_text())
            payload["run_dir"] = f"runs/{name}"
            result_path.write_text(json.dumps(payload))
        shutil.rmtree(self.other / "build" / "b")
        plan = plan_combine(self.root, self.flow, None, [a, b])
        self.assertEqual(
            plan.input_paths(),
            [
                str(self.other / "build" / "a" / "cov_build.vdb"),
                str(a / "cov" / "merged.vdb"),
                str(b / "cov" / "merged.vdb"),
            ],
        )
        payload = plan.manifest_payload(self.root)
        self.assertIsNone(payload["input_runs"][1]["design_db"])


class MergePhaseWithPlan(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-union-stage-"))
        self.flow = make_flow(self.root)
        write_run(self.root, "a", framework="cocotb")
        write_run(self.root, "b", framework="uvm", fingerprint="fp-uvm")
        self.plan = plan_combine(self.root, self.flow, None, [Path("runs/a"), Path("runs/b")])
        self.run_dir = self.root / "runs" / "union"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def merge(self, tool_cov: dict) -> int:
        stage_dir = self.run_dir / "stages" / "cov_merge"
        with mock.patch("runlib.stages._coverage_tool_version", return_value="vcs X"):
            return coverage_stage(
                self.flow,
                self.root,
                {"coverage": {TOOL: tool_cov}},
                TOOL,
                self.run_dir,
                "merge",
                make_args(self.plan),
                stage_dir / "logs" / "cov_merge.log",
                stage_dir / "scripts" / "cov_merge.sh",
                stage_dir / "env" / "cov_merge.env",
                True,
            )

    def test_combine_command_sees_every_database_and_the_manifest_names_the_runs(self):
        tool_cov = {
            "backend": "urg",
            "parser": "urg",
            "merged_name": "merged.vdb",
            "merge_cmd": ["false"],
            "combine_cmd": [sys.executable, "-c", MERGE_STUB, "{merged}", "{inputs}"],
        }
        self.assertEqual(self.merge(tool_cov), 0)
        merged = self.run_dir / "cov" / "merged.vdb"
        self.assertEqual(
            (merged / "inputs.txt").read_text().split(),
            self.plan.input_paths(),
        )
        manifest = json.loads((self.run_dir / "cov" / "coverage.json").read_text())
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(manifest["selection_source"], "run_dirs")
        self.assertEqual([entry["item"] for entry in manifest["inputs"]], ["run:a", "run:b"])
        self.assertEqual(manifest["combine"]["commit"], COMMIT)
        self.assertEqual(manifest["combine"]["frameworks"], ["cocotb", "uvm"])
        self.assertEqual(manifest["target"], "default")
        self.assertIsNone(manifest["build_fingerprint"])

    def test_missing_combine_command_is_a_config_error(self):
        tool_cov = {
            "backend": "urg",
            "parser": "urg",
            "merged_name": "merged.vdb",
            "merge_cmd": ["false"],
        }
        with self.assertRaisesRegex(ConfigError, "combine_cmd"):
            self.merge(tool_cov)


class CombineOptions(unittest.TestCase):
    def test_selection_and_run_flags_are_refused(self):
        base = ["--dut", DUT, "--cov-combine", "runs/a", "runs/b"]
        validate_combine_options(parse_args(base))
        validate_combine_options(parse_args([*base, "--fail-under", "90", "--dry-run"]))
        for extra, flag in (
            (["--items", "t"], "--items"),
            (["--stage", "cov_merge"], "--stage"),
            (["--reseed", "3"], "--reseed"),
            (["--waive"], "--waive"),
            (["--rebuild"], "--rebuild"),
        ):
            with self.subTest(flag):
                with self.assertRaisesRegex(ConfigError, flag):
                    validate_combine_options(parse_args([*base, *extra]))


if __name__ == "__main__":
    unittest.main()
