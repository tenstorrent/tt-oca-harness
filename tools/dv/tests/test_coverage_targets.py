# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the coverage merge of a run whose leaves span several build targets.

Each target's leaves merge against that target's design database, found in the model
directory the leaves recorded, and the per-target databases then merge with the tool's
`combine_cmd`, largest design database first. The models of a run's targets must not share
one directory.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import validate_target_builds  # noqa: E402
from runlib.coverage import CoverageError, CoverageInput  # noqa: E402
from runlib.models import ConfigError, Dut  # noqa: E402
from runlib.stages import (  # noqa: E402
    _union_fingerprint,
    coverage_stage,
    shared_model_dirs,
    validate_coverage_plan,
)
from test_json_contract import MANIFEST_TARGET_KEYS  # noqa: E402

DUT = "fixture"
TOOL = "vcs"

# Stand-in for a merge or union command: creates the database named by its first argument
# and records the rest of its arguments in it.
MERGE_STUB = (
    "import pathlib, sys\n"
    "out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)\n"
    "(out / 'inputs.txt').write_text('\\n'.join(sys.argv[2:]) + '\\n')\n"
)
# The same, failing for target `t2`'s merge.
FAILING_T2_STUB = "import sys\nif '/t2/' in sys.argv[1]: sys.exit(3)\n" + MERGE_STUB
# The same, reporting the instances it cannot align as URG does.
UNION_STUB = MERGE_STUB + (
    "print('Warning-[UCAPI-INSTANCEMISMATCH] Instance mismatch')\n"
    "print('Warning-[UCAPI-INSTANCEMISMATCH] Instance mismatch')\n"
    "print('Warning-[UCAPI-MAP-SHAPEMISMATCH] Shape mismatch')\n"
    "print('Note-[URG-RDG] Report directory generated')\n"
)
UNION_WARNINGS = {"UCAPI-INSTANCEMISMATCH": 2, "UCAPI-MAP-SHAPEMISMATCH": 1}


def make_flow(root: Path, framework: str = "uvm", raw: dict | None = None) -> Dut:
    return Dut(
        name=DUT,
        kind="sim",
        description="multi-target fixture",
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


def make_args(**overrides) -> Namespace:
    values = {
        "dry_run": False,
        "verbose": False,
        "timeout": None,
        "fail_under": None,
        "quiet": True,
        "rebuild": False,
        "cov": True,
        "_simulators": {TOOL: {"supports_cov": ["line"]}},
    }
    values.update(overrides)
    return Namespace(**values)


def tool_cov(merge=MERGE_STUB, union=UNION_STUB, **overrides) -> dict:
    cfg = {
        "backend": "urg",
        "parser": "urg",
        "merged_name": "merged.vdb",
        "design_artifact": "{build_cov_dir}",
        "merge_cmd": [sys.executable, "-c", merge, "{merged}", "{design_db}", "{inputs}"],
        "combine_cmd": [sys.executable, "-c", union, "{merged}", "{inputs}"],
    }
    cfg.update(overrides)
    return {key: value for key, value in cfg.items() if value is not None}


class TargetMerge(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-targets-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.flow = make_flow(self.root)
        self.run_dir = self.root / "runs" / "multi"
        self.stage_dir = self.run_dir / "stages" / "cov_merge"

    def model(self, target: str, *, design_db: bool = True) -> Path:
        build_dir = self.root / "build" / target / "fp"
        build_dir.mkdir(parents=True, exist_ok=True)
        if design_db:
            (build_dir / "cov_build.vdb").mkdir(exist_ok=True)
            (build_dir / "cov_build.vdb" / "db").write_text("x")
        return build_dir

    def leaf(self, item: str, target: str, *, build_dir: Path | None = None) -> Path:
        leaf_dir = self.run_dir / item / "seed_1" / "attempt_0"
        database = leaf_dir / "coverage" / "simv.vdb"
        database.mkdir(parents=True)
        (database / "db").write_text("x")
        target_build = {"target": target, "fingerprint": f"fp-{target}"}
        if build_dir is not None:
            target_build["build_dir"] = str(build_dir)
        (leaf_dir / "result.json").write_text(
            json.dumps(
                {
                    "item": item,
                    "seed": 1,
                    "attempt": 0,
                    "status": "PASS",
                    "flow": DUT,
                    "tool": TOOL,
                    "target": target,
                    "target_build": target_build,
                    "artifacts": {"coverage": str(database)},
                }
            )
        )
        return database

    def two_targets(self) -> dict[str, list[Path]]:
        t1, t2 = self.model("t1"), self.model("t2")
        return {
            "t1": [self.leaf("a", "t1", build_dir=t1), self.leaf("b", "t1", build_dir=t1)],
            "t2": [self.leaf("c", "t2", build_dir=t2)],
        }

    def merge(self, cov: dict, args: Namespace | None = None, design_db: Path | None = None) -> int:
        # The stage runs on the first planned target's config, so the run-level design
        # database is t1's; a merge of other targets reads each one's own from its leaves.
        with (
            mock.patch("runlib.stages._coverage_tool_version", return_value="vcs X"),
            mock.patch("runlib.stages._coverage_design_db", return_value=design_db),
        ):
            return coverage_stage(
                self.flow,
                self.root,
                {"coverage": {TOOL: cov}, "defaults": {"target": "t1"}},
                TOOL,
                self.run_dir,
                "merge",
                args or make_args(),
                self.stage_dir / "logs" / "cov_merge.log",
                self.stage_dir / "scripts" / "cov_merge.sh",
                self.stage_dir / "env" / "cov_merge.env",
                True,
            )

    def manifest(self) -> dict:
        return json.loads((self.run_dir / "cov" / "coverage.json").read_text())

    def recorded(self, database: Path) -> list[str]:
        return (database / "inputs.txt").read_text().split()

    def test_each_target_merges_against_its_own_design_database_then_the_union(self):
        leaves = self.two_targets()
        self.assertEqual(self.merge(tool_cov()), 0)
        cov = self.run_dir / "cov"
        design = {t: str(self.root / "build" / t / "fp" / "cov_build.vdb") for t in leaves}
        for target, databases in leaves.items():
            self.assertEqual(
                self.recorded(cov / "targets" / target / "merged.vdb"),
                [design[target], *sorted(str(path) for path in databases)],
            )
        self.assertEqual(
            self.recorded(cov / "merged.vdb"),
            [
                design["t1"],
                design["t2"],
                str(cov / "targets" / "t1" / "merged.vdb"),
                str(cov / "targets" / "t2" / "merged.vdb"),
            ],
        )
        manifest = self.manifest()
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(manifest["merge_return_code"], 0)
        self.assertIsNone(manifest["target"])
        self.assertRegex(manifest["build_fingerprint"], r"^[0-9a-f]{12}$")
        self.assertNotIn("design_db", manifest["artifacts"])
        self.assertEqual(
            sorted(entry["target"] for entry in manifest["inputs"]), ["t1"] * 2 + ["t2"]
        )
        self.assertEqual([entry["target"] for entry in manifest["targets"]], ["t1", "t2"])
        for entry in manifest["targets"]:
            self.assertEqual(set(entry), MANIFEST_TARGET_KEYS)
        first = manifest["targets"][0]
        self.assertEqual(first["build_fingerprint"], "fp-t1")
        self.assertEqual(first["inputs"], 2)
        self.assertEqual(first["merge_return_code"], 0)
        self.assertEqual(first["design_db"], "build/t1/fp/cov_build.vdb")
        self.assertEqual(first["merged"], "runs/multi/cov/targets/t1/merged.vdb")
        self.assertEqual(first["log"], "runs/multi/stages/cov_merge/logs/cov_merge.t1.log")
        self.assertTrue((self.stage_dir / "logs" / "cov_merge.t1.log").is_file())
        self.assertTrue((self.stage_dir / "scripts" / "cov_merge.t2.sh").is_file())
        self.assertEqual(manifest["union_warnings"], UNION_WARNINGS)
        self.assertNotIn("graded_summary", manifest)

    def test_the_union_reads_the_largest_design_database_first(self):
        self.two_targets()
        (self.root / "build" / "t2" / "fp" / "cov_build.vdb" / "big").write_bytes(b"x" * 64)
        self.assertEqual(self.merge(tool_cov()), 0)
        cov = self.run_dir / "cov"
        self.assertEqual(
            self.recorded(cov / "merged.vdb"),
            [
                str(self.root / "build" / "t2" / "fp" / "cov_build.vdb"),
                str(self.root / "build" / "t1" / "fp" / "cov_build.vdb"),
                str(cov / "targets" / "t2" / "merged.vdb"),
                str(cov / "targets" / "t1" / "merged.vdb"),
            ],
        )
        self.assertEqual([entry["target"] for entry in self.manifest()["targets"]], ["t2", "t1"])

    def test_the_summary_setting_names_the_graded_table_and_the_command_line_overrides_it(self):
        self.two_targets()
        for summary, cli, graded in (
            ("module_definition", None, "module_definition"),
            ("module_definition", "hierarchy", None),
            (None, "module_definition", "module_definition"),
        ):
            with self.subTest(summary=summary, cli=cli):
                self.assertEqual(
                    self.merge(tool_cov(summary=summary), make_args(cov_summary=cli)), 0
                )
                self.assertEqual(self.manifest().get("graded_summary"), graded)
        with self.assertRaisesRegex(
            ConfigError, r"the `module_definition` summary is a URG report table"
        ):
            self.merge(tool_cov(parser="imc", summary="module_definition"))

    def test_one_target_keeps_the_single_merge(self):
        build_dir = self.model("t1")
        database = self.leaf("a", "t1", build_dir=build_dir)
        self.assertEqual(self.merge(tool_cov(), design_db=build_dir / "cov_build.vdb"), 0)
        self.assertFalse((self.run_dir / "cov" / "targets").exists())
        self.assertEqual(
            self.recorded(self.run_dir / "cov" / "merged.vdb"),
            [str(build_dir / "cov_build.vdb"), str(database)],
        )
        manifest = self.manifest()
        self.assertEqual(manifest["target"], "t1")
        self.assertEqual(manifest["artifacts"]["design_db"], "build/t1/fp/cov_build.vdb")
        self.assertNotIn("targets", manifest)
        self.assertNotIn("union_warnings", manifest)

    def test_the_one_target_that_left_coverage_merges_against_its_own_design_database(self):
        t1, t2 = self.model("t1"), self.model("t2")
        database = self.leaf("c", "t2", build_dir=t2)
        self.assertEqual(self.merge(tool_cov(), design_db=t1 / "cov_build.vdb"), 0)
        self.assertEqual(
            self.recorded(self.run_dir / "cov" / "merged.vdb"),
            [str(t2 / "cov_build.vdb"), str(database)],
        )
        manifest = self.manifest()
        self.assertEqual(manifest["target"], "t2")
        self.assertEqual(manifest["artifacts"]["design_db"], "build/t2/fp/cov_build.vdb")
        self.assertNotIn("targets", manifest)

    def test_a_named_design_database_serves_a_lone_target_of_another_name(self):
        named = self.model("named") / "cov_build.vdb"
        database = self.leaf("c", "t2", build_dir=self.model("t2"))
        self.assertEqual(self.merge(tool_cov(design_db=str(named)), design_db=named), 0)
        self.assertEqual(
            self.recorded(self.run_dir / "cov" / "merged.vdb"), [str(named), str(database)]
        )
        manifest = self.manifest()
        self.assertEqual(manifest["target"], "t2")
        self.assertEqual(manifest["artifacts"]["design_db"], "build/named/fp/cov_build.vdb")

    def test_a_failed_target_merge_stops_before_the_union(self):
        self.two_targets()
        self.assertEqual(self.merge(tool_cov(merge=FAILING_T2_STUB)), 3)
        manifest = self.manifest()
        self.assertEqual(manifest["status"], "ERROR")
        self.assertEqual(manifest["merge_return_code"], 3)
        self.assertEqual(
            [(entry["target"], entry["merge_return_code"]) for entry in manifest["targets"]],
            [("t1", 0), ("t2", 3)],
        )
        self.assertFalse((self.run_dir / "cov" / "merged.vdb").exists())
        self.assertNotIn("union_warnings", manifest)

    def test_several_targets_need_a_combine_command(self):
        self.two_targets()
        with self.assertRaisesRegex(ConfigError, r"combine_cmd is required .*\(t1, t2\)"):
            self.merge(tool_cov(combine_cmd=None))
        with self.assertRaisesRegex(
            ConfigError, r"combine_cmd cannot use \{design_db\} to merge several targets"
        ):
            self.merge(tool_cov(combine_cmd=["urg", "-dir", "{design_db}", "-dir", "{inputs}"]))

    def test_a_run_that_cannot_union_its_targets_is_refused_before_it_simulates(self):
        def plan(cov: dict, targets: list[str]) -> None:
            validate_coverage_plan({"coverage": {TOOL: cov}}, TOOL, make_args(), targets)

        plan(tool_cov(), ["t1", "t2"])
        plan(tool_cov(combine_cmd=None), ["t1"])
        plan(tool_cov(combine_cmd=None), [])
        with self.assertRaisesRegex(ConfigError, r"combine_cmd is required .*\(t1, t2\)"):
            plan(tool_cov(combine_cmd=None), ["t1", "t2"])
        with self.assertRaisesRegex(ConfigError, r"combine_cmd cannot use \{design_db\}"):
            plan(tool_cov(combine_cmd=["urg", "-dir", "{design_db}"]), ["t1", "t2"])

    def test_one_named_design_database_cannot_serve_several_targets(self):
        self.two_targets()
        with self.assertRaisesRegex(ConfigError, "design_db names one design database"):
            self.merge(tool_cov(design_db="build/one/cov_build.vdb"))

    def test_a_target_needs_its_model_directory_and_design_database(self):
        t1 = self.model("t1")
        self.leaf("a", "t1", build_dir=t1)
        self.leaf("c", "t2")
        with self.assertRaisesRegex(
            CoverageError, r"inputs of target `t2` record 0 model directories"
        ):
            self.merge(tool_cov())
        shutil.rmtree(self.run_dir / "c")
        self.leaf("c", "t2", build_dir=self.model("t2", design_db=False))
        with self.assertRaisesRegex(CoverageError, "design coverage database of target `t2`"):
            self.merge(tool_cov())

    def test_a_dry_run_renders_every_target_merge_and_the_union(self):
        cov = tool_cov(
            merge_cmd=["urg", "-dir", "{design_db}", "-dir", "{inputs}", "-dbname", "{merged}"],
            combine_cmd=["urg", "-flex_merge", "union", "-dir", "{inputs}", "-dbname", "{merged}"],
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = self.merge(cov, make_args(dry_run=True, _planned_targets=["t1", "t2"]))
        self.assertEqual(rc, 0)
        commands = [line for line in out.getvalue().splitlines() if line.startswith("CMD  :")]
        merged = self.run_dir / "cov"
        self.assertEqual(
            commands,
            [
                f"CMD  : urg -dir '<design database of {target}>' "
                f"-dir '<coverage inputs of {target}>' "
                f"-dbname {merged}/targets/{target}/merged.vdb"
                for target in ("t1", "t2")
            ]
            + [
                "CMD  : urg -flex_merge union -dir '<design database of t1>' "
                f"-dir '<design database of t2>' -dir {merged}/targets/t1/merged.vdb "
                f"-dir {merged}/targets/t2/merged.vdb -dbname {merged}/merged.vdb"
            ],
        )
        self.assertFalse(self.run_dir.exists())


def built(target: str, fingerprint: str | None) -> CoverageInput:
    return CoverageInput(
        path=f"runs/{target}/simv.vdb",
        item="t",
        seed=1,
        attempt=0,
        status="PASS",
        target=target,
        build_fingerprint=fingerprint,
        result_json=None,
        source="result_json",
    )


class UnionFingerprint(unittest.TestCase):
    def test_a_target_joining_leaving_or_rebuilding_changes_it(self):
        base = _union_fingerprint({"t1": [built("t1", "fp1")], "t2": [built("t2", "fp2")]})
        self.assertEqual(
            base, _union_fingerprint({"t2": [built("t2", "fp2")], "t1": [built("t1", "fp1")]})
        )
        for groups in (
            {"t1": [built("t1", "fp1")], "t2": [built("t2", "fp9")]},
            {"t1": [built("t1", "fp1")], "t3": [built("t3", "fp2")]},
            {"t1": [built("t1", "fp1")], "t2": [built("t2", "fp2")], "t3": [built("t3", None)]},
        ):
            with self.subTest(groups=sorted(groups)):
                self.assertNotEqual(_union_fingerprint(groups), base)


def stage_flow(root: Path, framework: str) -> Dut:
    return make_flow(
        root, framework, {"native": {"stages": {"hdl_compile": {"kind": "hdl_compile"}}}}
    )


def target_cfg(build_dir: str, *, cache: bool = False, work_dir: str | None = None) -> dict:
    build = {"options": {"cache_enabled": cache}, "work_dir": work_dir or build_dir}
    return {
        "build": build,
        "defaults": {"target": "t"},
        "targets": {"t": {"build_dir": build_dir}},
    }


class SharedModelDirectories(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-model-dirs-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def shared(self, framework: str, tool: str, cfgs: dict) -> dict:
        return shared_model_dirs(stage_flow(self.root, framework), self.root, tool, cfgs)

    def test_targets_on_one_uncached_directory_are_named(self):
        cfgs = {"a": target_cfg("build/x"), "b": target_cfg("build/x"), "c": target_cfg("build/y")}
        self.assertEqual(self.shared("uvm", "vcs", cfgs), {(self.root / "build" / "x"): ["a", "b"]})
        self.assertEqual(
            self.shared("cocotb", "verilator", cfgs), {(self.root / "build" / "x"): ["a", "b"]}
        )

    def test_the_build_cache_or_a_target_directory_keeps_models_apart(self):
        cached = {"a": target_cfg("build/x", cache=True), "b": target_cfg("build/x", cache=True)}
        self.assertEqual(self.shared("uvm", "vcs", cached), {})
        uncached = {"a": target_cfg("build/x"), "b": target_cfg("build/x")}
        # cocotb on VCS builds each target below a directory named for it.
        self.assertEqual(self.shared("cocotb", "vcs", uncached), {})

    def test_the_run_is_refused_naming_the_targets_and_the_fixes(self):
        flow = stage_flow(self.root, "uvm")
        cfgs = {"a": target_cfg("build/x"), "b": target_cfg("build/x")}
        with self.assertRaisesRegex(
            ConfigError,
            r"targets `a`, `b` build into one model directory, build/x\. Give each target "
            r"its own build_dir, set \[build\.options\] cache_enabled = true, or pass "
            r"--target NAME",
        ):
            validate_target_builds(flow, self.root, "vcs", cfgs)
        validate_target_builds(flow, self.root, "vcs", {"a": target_cfg("build/x")})

    def test_uvm_builds_key_on_the_work_directory(self):
        cfgs = {
            "a": target_cfg("build/x", work_dir="build/x/a"),
            "b": target_cfg("build/x", work_dir="build/x/b"),
        }
        self.assertEqual(self.shared("uvm", "vcs", cfgs), {})
        self.assertEqual(
            self.shared("cocotb", "verilator", cfgs), {(self.root / "build" / "x"): ["a", "b"]}
        )


if __name__ == "__main__":
    unittest.main()
