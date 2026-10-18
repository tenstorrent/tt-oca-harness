# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the Verilator SV-UVM stages: the dispatch, the build and sim commands they
render in dry run, and the build fingerprint.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import stages  # noqa: E402
from runlib.cli import parse_args  # noqa: E402
from runlib.config import load_simulators, load_test_catalog, merge_simulator_defaults  # noqa: E402
from runlib.duts import resolve_dut  # noqa: E402
from runlib.models import Dut, TestCatalog  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
UVM_SRC = REPO_ROOT / "vendor" / "accellera" / "uvm-core" / "upstream" / "src"


class Dispatch(unittest.TestCase):
    def test_uvm_on_verilator_builds_and_runs_the_verilator_model(self):
        resolve = stages._resolve_stage_kind
        self.assertEqual(resolve("hdl_compile", "uvm", "verilator", "f"), "verilator_uvm_build")
        self.assertEqual(resolve("sim", "uvm", "verilator", "f"), "verilator_uvm_sim")
        self.assertEqual(resolve("hdl_compile", "cocotb", "verilator", "f"), "cocotb_build")
        with self.assertRaisesRegex(stages.ConfigError, "no `sim` adapter for tool `xcelium`"):
            resolve("sim", "uvm", "xcelium", "f")

    def test_the_registry_lets_verilator_run_uvm(self):
        self.assertIn("uvm", load_simulators(REPO_ROOT)["verilator"]["frameworks"])


class Commands(unittest.TestCase):
    """The commands the stages render for the DTP SV-UVM view on Verilator."""

    flow: Dut
    sim_cfg: dict[str, Any]
    catalog: TestCatalog
    item: str
    top: str

    @classmethod
    def setUpClass(cls):
        cls.flow = resolve_dut(REPO_ROOT, "dtp", framework="uvm")
        cls.sim_cfg = merge_simulator_defaults(
            cls.flow.raw, load_simulators(REPO_ROOT), ["verilator"]
        )
        cls.catalog = load_test_catalog(cls.flow, REPO_ROOT)
        cls.item = sorted(cls.catalog.tests)[0]
        cls.top = stages.build_cfg(cls.flow, cls.sim_cfg)["top_module"]

    def setUp(self):
        self.leaf = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.leaf, ignore_errors=True)
        patches = (
            mock.patch.dict(os.environ, {"OCAH_UVM_HOME": ""}),
            mock.patch.object(stages, "verilator_version", return_value="Verilator 5.052"),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def args(self, *extra: str):
        return parse_args(
            ["--dut", "dtp", "--framework", "uvm", "--tool", "verilator", "--dry-run", *extra]
        )

    def launched(self, run) -> list[str]:
        """The one command ``run`` hands to run_subprocess."""
        launches: list[list[str]] = []

        def launch(argv, *call_args, **kwargs) -> int:
            launches.append([str(part) for part in argv])
            return 0

        with (
            mock.patch.object(stages, "run_subprocess", side_effect=launch),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run(), 0)
        self.assertEqual(len(launches), 1)
        return launches[0]

    def build(self, args) -> list[str]:
        return self.launched(
            lambda: stages.verilator_uvm_build(
                self.flow,
                REPO_ROOT,
                self.sim_cfg,
                args,
                self.leaf / "build.log",
                self.leaf / "build.sh",
                self.leaf / "build.env",
            )
        )

    def sim(self, args, test_args: list[str]) -> list[str]:
        return self.launched(
            lambda: stages.verilator_uvm_sim(
                self.flow,
                REPO_ROOT,
                self.sim_cfg,
                self.catalog,
                self.item,
                args,
                self.leaf,
                self.leaf / "sim.log",
                self.leaf / "sim.sh",
                self.leaf / "sim.env",
                7,
                test_args=test_args,
            )
        )

    def test_the_build_verilates_the_library_ahead_of_the_filelist_into_one_model(self):
        argv = self.build(self.args())
        self.assertEqual(argv[:2], ["verilator", "--binary"])
        self.assertEqual(argv[argv.index("--top-module") + 1], self.top)
        self.assertEqual(argv[argv.index("-o") + 1], f"V{self.top}")
        self.assertTrue(argv[argv.index("-Mdir") + 1].endswith("/build/uvm/verilator"))
        self.assertIn(f"+incdir+{UVM_SRC}", argv)
        self.assertLess(argv.index(str(UVM_SRC / "uvm_pkg.sv")), argv.index("-f"))
        self.assertIn("+define+UVM", argv)

    def test_the_build_gives_untimed_sources_the_vcs_timescale(self):
        argv = self.build(self.args())
        self.assertEqual(argv[argv.index("--timescale") + 1], "1ns/1ps")

    def test_the_build_compiles_the_library_dpi_layer_with_the_vpi(self):
        argv = self.build(self.args())
        self.assertIn("--vpi", argv)
        dpi = argv.index(str(UVM_SRC / "dpi" / "uvm_dpi.cc"))
        self.assertEqual(argv[dpi + 1 : dpi + 3], ["-CFLAGS", "-DUVM_NO_MALLOC"])

    def test_a_coverage_build_takes_the_view_coverage_args_in_a_sibling_directory(self):
        argv = self.build(self.args("--cov"))
        configured = stages._render_list(
            stages.coverage_cfg(self.sim_cfg)["verilator"]["build_args"],
            {"repo_root": str(REPO_ROOT)},
        )
        top = argv.index("--top-module")
        self.assertEqual(argv[top - len(configured) : top], configured)
        self.assertTrue(argv[argv.index("-Mdir") + 1].endswith("/build/uvm/verilator-coverage"))

    def test_the_sim_runs_the_model_with_the_test_and_both_seeds(self):
        argv = self.sim(self.args(), ["+knob=1"])
        test = self.catalog.tests[self.item]
        self.assertTrue(argv[0].endswith(f"/build/uvm/verilator/V{self.top}"))
        self.assertEqual(
            argv[1:],
            [
                f"+UVM_TESTNAME={test.module or test.name}",
                "+verilator+seed+7",
                "+ntb_random_seed=7",
                "+knob=1",
            ],
        )

    def test_a_caller_testname_replaces_the_testlist_one(self):
        argv = self.sim(self.args(), ["+UVM_TESTNAME=derived_test"])
        self.assertEqual(
            [arg for arg in argv if "UVM_TESTNAME" in arg], ["+UVM_TESTNAME=derived_test"]
        )

    def test_a_coverage_sim_writes_its_data_in_the_leaf(self):
        argv = self.sim(self.args("--cov"), [])
        self.assertIn(f"+verilator+coverage+file+{self.leaf}/coverage/coverage.dat", argv)
        self.assertTrue(argv[0].endswith(f"/build/uvm/verilator-coverage/V{self.top}"))

    def test_a_wave_request_is_refused(self):
        with (
            mock.patch.object(stages, "_wave_format", return_value="fst"),
            self.assertRaisesRegex(stages.ConfigError, "dumps no waves"),
        ):
            self.build(self.args())

    def uvm_home(self, text: str) -> Path:
        home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        (home / "src").mkdir()
        (home / "src" / "uvm_pkg.sv").write_text(text)
        return home

    def fingerprint(self, home: Path) -> str:
        with mock.patch.dict(os.environ, {"OCAH_UVM_HOME": str(home)}):
            info = stages._verilator_uvm_resolve_build(
                self.flow, REPO_ROOT, self.sim_cfg, self.args()
            )
        return str(info["fingerprint"])

    def test_the_fingerprint_follows_the_library_content_not_its_path(self):
        text = "package uvm_pkg;\nendpackage\n"
        home = self.uvm_home(text)
        before = self.fingerprint(home)
        self.assertEqual(self.fingerprint(self.uvm_home(text)), before)
        (home / "src" / "uvm_pkg.sv").write_text("package uvm_pkg;\n// edited\nendpackage\n")
        self.assertNotEqual(self.fingerprint(home), before)


if __name__ == "__main__":
    unittest.main()
