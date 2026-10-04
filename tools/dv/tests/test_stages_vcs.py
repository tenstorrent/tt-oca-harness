# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the VCS stage helpers (cocotb runner build args, UVM precompile) and the
build identity a leaf on a pre-built model reports.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import stages  # noqa: E402
from runlib.cli import parse_args  # noqa: E402
from runlib.config import load_simulators, load_test_catalog, merge_simulator_defaults  # noqa: E402
from runlib.duts import resolve_dut  # noqa: E402
from runlib.logparse import validate_parser_registry  # noqa: E402
from runlib.models import Dut, TestCatalog, TestEntry  # noqa: E402
from runlib.stages import (  # noqa: E402
    COCOTB_RUNNER_TOOLS,
    COCOTB_VCS_DEFAULT_ACCESS,
    _build_jobs_arg,
    _cocotb_build_args,
    _last_plusarg_wins,
    _prebuilt_target_build,
    _uvm_testname_override,
    _vcs_cocotb_access,
    _vcs_uvm_precompile_cmd,
    cocotb_vcs_access,
    expand_ocah_vendor_define_aliases,
    mark_cocotb_prebuilt,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def make_args(define: list | None = None) -> Namespace:
    return Namespace(define=define)


class VcsUvmPrecompileCmd(unittest.TestCase):
    def test_default_lib_and_no_defines(self):
        cmd = _vcs_uvm_precompile_cmd({}, {}, make_args())
        self.assertEqual(cmd, "vlogan -full64 -ntb_opts uvm-1.2")

    def test_uvm_lib_override(self):
        cmd = _vcs_uvm_precompile_cmd({"uvm_lib": "uvm-1.2p1"}, {}, make_args())
        self.assertEqual(cmd, "vlogan -full64 -ntb_opts uvm-1.2p1")

    def test_target_defines_reach_the_precompile(self):
        cmd = _vcs_uvm_precompile_cmd(
            {}, {"defines": ["UVM_PACKER_MAX_BYTES=1600000"]}, make_args()
        )
        self.assertIn("+define+UVM_PACKER_MAX_BYTES=1600000", cmd.split())

    def test_cli_defines_append_after_target_defines(self):
        cmd = _vcs_uvm_precompile_cmd(
            {},
            {"defines": ["UVM_PACKER_MAX_BYTES=1600000"]},
            make_args(define=["EXTRA_CLI_DEFINE=1"]),
        )
        tokens = cmd.split()
        self.assertLess(
            tokens.index("+define+UVM_PACKER_MAX_BYTES=1600000"),
            tokens.index("+define+EXTRA_CLI_DEFINE=1"),
        )

    def test_quoted_define_value_survives_bash_embedding(self):
        # The precompile line is embedded in a `bash -c` script; a define whose
        # value carries double quotes (an include-hook filename) must reach
        # vlogan with the quotes intact.
        cmd = _vcs_uvm_precompile_cmd(
            {}, {"defines": ['HOOK_TESTS="overlay_tests.svh"']}, make_args()
        )
        self.assertIn("'+define+HOOK_TESTS=\"overlay_tests.svh\"'", cmd)

    def test_matches_user_source_analysis_defines(self):
        # The precompile must carry exactly the tokens _vcs_defines emits for
        # the user-source vlogan, in the same order.
        from runlib.stages import _vcs_defines

        target = {"defines": ["A=1", "B"]}
        args = make_args(define=["C=3"])
        expected = _vcs_defines(target, args)
        cmd = _vcs_uvm_precompile_cmd({}, target, args)
        self.assertEqual(cmd.split()[4:], expected)


class UvmTestnameOverride(unittest.TestCase):
    def test_absent_returns_empty(self):
        self.assertEqual(_uvm_testname_override(["+ntb_random_seed=1", "+FOO=2"]), "")

    def test_supplied_value_returned(self):
        self.assertEqual(
            _uvm_testname_override(["+FOO=1", "+UVM_TESTNAME=my_overlay_test"]),
            "my_overlay_test",
        )

    def test_first_supplied_value_wins(self):
        # Mirrors UVM's first-occurrence-wins semantics for the plusarg.
        self.assertEqual(_uvm_testname_override(["+UVM_TESTNAME=a", "+UVM_TESTNAME=b"]), "a")

    def test_prefix_must_match_exactly(self):
        self.assertEqual(_uvm_testname_override(["+UVM_TESTNAME_X=a"]), "")


class LastPlusargWins(unittest.TestCase):
    def test_later_scalar_wins(self):
        self.assertEqual(
            _last_plusarg_wins(["+FOO=1", "+BAR=2", "+FOO=3"]),
            ["+BAR=2", "+FOO=3"],
        )

    def test_bare_flags_and_non_plusargs_kept(self):
        self.assertEqual(
            _last_plusarg_wins(["-sv", "+FOO", "+FOO=1", "+FOO=2"]),
            ["-sv", "+FOO", "+FOO=2"],
        )

    def test_repeated_uvm_set_plusargs_are_kept(self):
        rendered = [
            "+uvm_set_type_override=src_a,dst_a",
            "+FOO=1",
            "+uvm_set_type_override=src_b,dst_b",
            "+FOO=2",
            "+uvm_set_verbosity=*,UVM_LOW",
        ]
        self.assertEqual(
            _last_plusarg_wins(rendered),
            [
                "+uvm_set_type_override=src_a,dst_a",
                "+uvm_set_type_override=src_b,dst_b",
                "+FOO=2",
                "+uvm_set_verbosity=*,UVM_LOW",
            ],
        )


if __name__ == "__main__":
    unittest.main()


class PrebuiltBuildIdentity(unittest.TestCase):
    """A leaf on a model built earlier in the run reports that build's identity."""

    RECORDED = {
        "target": "default",
        "tool": "vcs",
        "build_dir": "/runs/model",
        "fingerprint": "efba240c5e52",
    }
    # What a leaf computes on a host where `vcs -ID` timed out: same model, other digest.
    DRIFTED = {
        "target_name": "default",
        "sim_build": Path("/runs/elsewhere"),
        "fingerprint": "c670ed085301",
        "filelist": None,
    }
    # The same drift as the native resolvers report it.
    DRIFTED_NATIVE = {
        "target_name": "default",
        "build_dir": Path("/runs/elsewhere"),
        "fingerprint": "c670ed085301",
    }
    # Each sim stage kind with its framework, tool, sim function, resolver and drifted answer.
    KINDS = {
        "cocotb_sim": ("cocotb", "vcs", "cocotb_sim", "_cocotb_build_info", DRIFTED),
        "vcs_sim": ("uvm", "vcs", "vcs_sim", "_vcs_resolve_build", DRIFTED_NATIVE),
        "xrun_sim": ("uvm", "xcelium", "xcelium_sim", "_xcelium_resolve_build", DRIFTED_NATIVE),
    }
    PASSING_UVM_LOG = (
        "UVM TEST PASSED\n--- UVM Report Summary ---\nUVM_ERROR :    0\nUVM_FATAL :    0\n"
    )

    @classmethod
    def setUpClass(cls):
        cls.policies = validate_parser_registry(REPO_ROOT)
        cls.simulators = load_simulators(REPO_ROOT)

    def test_a_prebuilt_target_returns_the_identity_its_build_recorded(self):
        args = Namespace()
        mark_cocotb_prebuilt(args, "default", self.RECORDED)
        self.assertEqual(_prebuilt_target_build(args, "default"), self.RECORDED)
        self.assertIsNone(_prebuilt_target_build(args, "other"))

    def test_a_target_marked_without_a_build_directory_has_no_identity(self):
        args = Namespace()
        mark_cocotb_prebuilt(args, "default")
        self.assertIsNone(_prebuilt_target_build(args, "default"))
        mark_cocotb_prebuilt(args, "default", {"fingerprint": "efba240c5e52"})
        self.assertIsNone(_prebuilt_target_build(args, "default"))

    def test_a_wave_debug_rerun_computes_its_own_identity(self):
        args = Namespace(_wave_debug_rerun=True)
        mark_cocotb_prebuilt(args, "default", self.RECORDED)
        self.assertIsNone(_prebuilt_target_build(args, "default"))

    def passing_sim(self, *call_args, **kwargs) -> int:
        """A native sim function whose leaf log grades as a passing UVM test."""
        log_path = Path(call_args[7])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(self.PASSING_UVM_LOG, encoding="utf-8")
        return 0

    def run_sim_leaf(self, args: Namespace, kind: str = "cocotb_sim"):
        framework, tool, sim_function, resolver, drifted = self.KINDS[kind]
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        raw = {"native": {"stages": {"sim": {"kind": kind}}}}
        flow = Dut(
            name="fixture",
            kind="sim",
            description="build identity fixture",
            framework=framework,
            visibility="public",
            runnability="runnable",
            license="Apache-2.0",
            root="dut",
            default_tool=tool,
            tools=[tool],
            path=self.root / "dut" / "fixture_sim_cfg.toml",
            raw=raw,
            frameworks=[framework],
            default_framework=framework,
        )
        catalog = TestCatalog(
            path=None, groups={}, tests={"t_x": TestEntry(name="t_x", module="t_x")}
        )
        sim = {"return_value": 0} if kind == "cocotb_sim" else {"side_effect": self.passing_sim}
        with (
            mock.patch.object(stages, sim_function, **sim),
            mock.patch.object(stages, resolver, return_value=drifted),
            mock.patch.object(stages, "_sim_test_args", return_value=[]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            return stages.run_stage(
                flow,
                self.root,
                raw,
                catalog,
                "sim",
                "t_x",
                args,
                tool,
                self.root / "run",
                self.simulators,
                self.policies,
            )

    def leaf_log(self, result) -> str:
        log = Path(result.log)
        return (log if log.is_absolute() else self.root / log).read_text(encoding="utf-8")

    def leaf_args(self) -> Namespace:
        return Namespace(
            dry_run=False,
            quiet=True,
            verbose=False,
            timeout=None,
            ui="plain",
            seed=None,
            sim_jobs=1,
            cov=False,
            waves=None,
            rebuild=False,
            run_mode=None,
        )

    def test_a_sim_leaf_records_the_build_identity_over_its_own_recomputation(self):
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                args = self.leaf_args()
                mark_cocotb_prebuilt(args, "default", self.RECORDED)
                result = self.run_sim_leaf(args, kind)
                target_build = result.metadata["target_build"]
                self.assertEqual(
                    (target_build["build_dir"], target_build["fingerprint"]),
                    ("/runs/model", "efba240c5e52"),
                )
                self.assertEqual(result.metadata["provenance"]["build_fingerprint"], "efba240c5e52")
                if kind != "cocotb_sim":
                    self.assertEqual(result.status, "PASS", result.reason)
                    self.assertRegex(
                        self.leaf_log(result), r"\nPROVENANCE .*build_fingerprint=efba240c5e52"
                    )

    def test_a_native_sim_leaf_runs_the_model_its_build_recorded_without_probing(self):
        flow = resolve_dut(REPO_ROOT, "dtp", framework="uvm")
        catalog = load_test_catalog(flow, REPO_ROOT)
        item = sorted(catalog.tests)[0]
        located = {
            "vcs": lambda argv: argv[0],
            "xcelium": lambda argv: argv[argv.index("-xmlibdirpath") + 1],
        }
        for tool, sim_function, probe in (
            ("vcs", stages.vcs_sim, "vcs_version"),
            ("xcelium", stages.xcelium_sim, "xcelium_version"),
        ):
            with self.subTest(tool=tool):
                sim_cfg = merge_simulator_defaults(flow.raw, self.simulators, [tool])
                args = parse_args(
                    ["--dut", "dtp", "--framework", "uvm", "--items", item, "--tool", tool]
                    + ["--dry-run"]
                )
                leaf = Path(tempfile.mkdtemp()).resolve()
                self.addCleanup(shutil.rmtree, leaf, ignore_errors=True)
                launches: list[list[str]] = []

                def launch(argv, *call_args, **kwargs) -> int:
                    launches.append([str(part) for part in argv])
                    return 0

                def simulate() -> int:
                    return sim_function(
                        flow,
                        REPO_ROOT,
                        sim_cfg,
                        catalog,
                        item,
                        args,
                        leaf,
                        leaf / "sim.log",
                        leaf / "sim.sh",
                        leaf / "sim.env",
                        1,
                    )

                with (
                    mock.patch.object(stages, probe, side_effect=AssertionError("probed")),
                    mock.patch.object(
                        stages, "_bender_sources_fingerprint", side_effect=AssertionError("read")
                    ),
                    mock.patch.object(stages, "run_subprocess", side_effect=launch),
                    redirect_stdout(io.StringIO()),
                ):
                    # Handed nothing, the leaf fingerprints the model itself, which probes.
                    with self.assertRaises(AssertionError):
                        simulate()
                    mark_cocotb_prebuilt(args, "default", self.RECORDED)
                    rc = simulate()
                self.assertEqual(rc, 0)
                self.assertEqual(len(launches), 1)
                self.assertEqual(
                    located[tool](launches[0]),
                    "/runs/model/simv" if tool == "vcs" else "/runs/model",
                )

    def test_a_sim_leaf_runs_the_model_its_build_recorded(self):
        flow = resolve_dut(REPO_ROOT, "dtp")
        sim_cfg = merge_simulator_defaults(flow.raw, self.simulators, ["verilator"])
        catalog = load_test_catalog(flow, REPO_ROOT)
        item = sorted(catalog.tests)[0]
        args = parse_args(["--dut", "dtp", "--items", item, "--tool", "verilator", "--dry-run"])
        mark_cocotb_prebuilt(args, "default", self.RECORDED)
        computed = stages._cocotb_build_info

        def drifted(*call_args, **kwargs):
            info = computed(*call_args, **kwargs)
            info["sim_build"] = self.DRIFTED["sim_build"]
            return info

        leaf = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, leaf, ignore_errors=True)
        console = io.StringIO()
        with (
            mock.patch.object(stages, "_cocotb_build_info", side_effect=drifted),
            redirect_stdout(console),
        ):
            rc = stages.cocotb_sim(
                flow,
                REPO_ROOT,
                sim_cfg,
                catalog,
                item,
                args,
                "verilator",
                leaf,
                leaf / "sim.log",
                leaf / "sim.sh",
                leaf / "sim.env",
                1,
            )
        self.assertEqual(rc, 0)
        builds = [line for line in console.getvalue().splitlines() if "build=" in line]
        self.assertTrue(builds and all("build=/runs/model " in line for line in builds), builds)

    def test_without_a_recorded_identity_the_leaf_keeps_its_own(self):
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                result = self.run_sim_leaf(self.leaf_args(), kind)
                self.assertEqual(result.metadata["target_build"]["fingerprint"], "c670ed085301")


class CocotbVcsRunnerBuildArgs(unittest.TestCase):
    """The cocotb VCS path builds through cocotb's Python runner like Verilator/Xcelium."""

    def _args(self, **overrides) -> Namespace:
        base = {"define": [], "comp_arg": [], "build_jobs": None, "sim_jobs": 1}
        base.update(overrides)
        return Namespace(**base)

    def test_vcs_is_a_python_runner_tool(self):
        self.assertIn("vcs", COCOTB_RUNNER_TOOLS)

    def test_timescale_target_flags_defines_and_filelist(self):
        build = {"vcs": {"timescale": "1ns/1ps"}}
        run_target = {"defines": ["SMU_TB"], "tools": {"vcs": {"flags": ["-assert", "svaext"]}}}
        argv = _cocotb_build_args(
            "vcs", None, Path("/repo"), build, run_target, {}, {}, Path("/repo/f.f"), self._args()
        )
        self.assertEqual(argv[0], "-timescale=1ns/1ps")
        self.assertEqual(argv[1:3], ["-assert", "svaext"])
        self.assertIn("+define+SMU_TB", argv)
        self.assertEqual(argv[-2:], ["-f", "/repo/f.f"])

    def test_no_timescale_when_unset(self):
        argv = _cocotb_build_args(
            "vcs", None, Path("/repo"), {}, {}, {}, {}, Path("/repo/f.f"), self._args()
        )
        self.assertFalse(any(arg.startswith("-timescale") for arg in argv))

    def test_build_jobs_and_cli_flags_reach_vcs(self):
        argv = _cocotb_build_args(
            "vcs",
            None,
            Path("/repo"),
            {"vcs": {"partition_compile": True}},
            {},
            {},
            {},
            Path("/repo/f.f"),
            self._args(define=["X=1"], comp_arg=["-lca"], build_jobs=8),
        )
        self.assertIn("-lca", argv)
        self.assertIn("+define+X=1", argv)
        self.assertIn("-j8", argv)
        self.assertIn("-partcomp", argv)


class BuildJobsDerivation(unittest.TestCase):
    """An omitted --build-jobs follows --sim-jobs, except that a cluster fan-out stops at this host."""

    def test_local_fan_out_is_the_build_fan_out(self):
        self.assertEqual(_build_jobs_arg(Namespace(build_jobs=None, sim_jobs=6)), 6)

    def test_explicit_build_jobs_win_on_a_cluster(self):
        args = Namespace(build_jobs=3, sim_jobs=64, _cluster_executor=True)
        self.assertEqual(_build_jobs_arg(args), 3)

    def test_cluster_fan_out_is_capped_at_the_host(self):
        cores = os.cpu_count() or 1
        wide = Namespace(build_jobs=None, sim_jobs=cores * 8, _cluster_executor=True)
        self.assertEqual(_build_jobs_arg(wide), cores)
        narrow = Namespace(build_jobs=None, sim_jobs=1, _cluster_executor=True)
        self.assertEqual(_build_jobs_arg(narrow), 1)


class OcahVendorDefineAliases(unittest.TestCase):
    def _args(self, **overrides) -> Namespace:
        base = {"define": [], "comp_arg": [], "build_jobs": None, "sim_jobs": 1}
        base.update(overrides)
        return Namespace(**base)

    def test_bare_simulation_gains_abr_alias(self):
        self.assertEqual(
            expand_ocah_vendor_define_aliases(["SIMULATION", "RANDOM=0"]),
            ["SIMULATION", "RANDOM=0", "ABR_SIMULATION"],
        )

    def test_plusdefine_verilator_gains_target_alias(self):
        self.assertEqual(
            expand_ocah_vendor_define_aliases(["+define+VERILATOR", "-Wno-fatal"]),
            ["+define+VERILATOR", "-Wno-fatal", "+define+TARGET_VERILATOR"],
        )

    def test_emulation_gains_pulp_assert_override(self):
        self.assertEqual(
            expand_ocah_vendor_define_aliases(["+define+EMULATION", "+define+SYNTHESIS"]),
            [
                "+define+EMULATION",
                "+define+SYNTHESIS",
                "+define+TARGET_SYNTHESIS",
                "+define+ASSERTS_OVERRIDE_ON",
            ],
        )

    def test_unrelated_defines_are_unchanged(self):
        self.assertEqual(expand_ocah_vendor_define_aliases(["A=1", "B"]), ["A=1", "B"])

    def test_cocotb_vcs_expands_simulation(self):
        argv = _cocotb_build_args(
            "vcs",
            None,
            Path("/repo"),
            {},
            {"defines": ["SIMULATION"]},
            {},
            {},
            Path("/repo/f.f"),
            self._args(),
        )
        self.assertIn("+define+SIMULATION", argv)
        self.assertIn("+define+ABR_SIMULATION", argv)

    def test_cocotb_verilator_expands_aliases_without_force_include(self):
        argv = _cocotb_build_args(
            "verilator",
            None,
            Path("/repo"),
            {},
            {
                "defines": ["SIMULATION"],
                "tools": {"verilator": {"flags": ["+define+VERILATOR"]}},
            },
            {},
            {},
            Path("/repo/f.f"),
            self._args(),
        )
        self.assertIn("+define+ABR_SIMULATION", argv)
        self.assertIn("+define+TARGET_VERILATOR", argv)
        self.assertNotIn("-FI", argv)


class CocotbVcsAccess(unittest.TestCase):
    """`[build.vcs].cocotb_access` replaces the debug access cocotb's Vcs runner grants."""

    def test_unset_key_or_a_waves_run_keeps_cocotb_access(self):
        build = {"vcs": {"cocotb_access": ["-debug_access+r+w"]}}
        self.assertEqual(_vcs_cocotb_access({}, False), [])
        self.assertEqual(_vcs_cocotb_access(build, True), [])
        self.assertEqual(_vcs_cocotb_access(build, False), ["-debug_access+r+w"])

    def test_build_opts_carry_the_configured_access_and_are_restored(self):
        try:
            from cocotb_tools import runner as cocotb_runner
        except ImportError:  # pragma: no cover - the dv dependency group supplies cocotb
            self.skipTest("cocotb_tools is not installed")
        original = cocotb_runner.Vcs.__dict__["_build_opts"]
        runner = cocotb_runner.Vcs.__new__(cocotb_runner.Vcs)
        runner.verbose = False
        default = runner._build_opts
        self.assertTrue(set(COCOTB_VCS_DEFAULT_ACCESS) <= set(default))
        with cocotb_vcs_access(["-debug_access+r+w"]):
            narrowed = runner._build_opts
        self.assertEqual(
            narrowed,
            [opt for opt in default if opt not in COCOTB_VCS_DEFAULT_ACCESS]
            + ["-debug_access+r+w"],
        )
        self.assertIs(cocotb_runner.Vcs.__dict__["_build_opts"], original)
        with cocotb_vcs_access([]):
            self.assertIs(cocotb_runner.Vcs.__dict__["_build_opts"], original)
