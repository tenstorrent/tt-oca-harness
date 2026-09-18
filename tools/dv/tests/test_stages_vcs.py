# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the VCS stage helpers (cocotb runner build args, UVM precompile).

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.stages import (  # noqa: E402
    COCOTB_RUNNER_TOOLS,
    _cocotb_build_args,
    _last_plusarg_wins,
    _uvm_testname_override,
    _vcs_uvm_precompile_cmd,
)


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
