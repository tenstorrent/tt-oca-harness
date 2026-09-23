# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the build fingerprint: what names a model directory.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.buildcache import (  # noqa: E402
    build_fingerprint,
    fingerprint_build_args,
    option_build_args,
    vcs_build_args,
    xcelium_build_args,
)

TOP = "sep_uvm_top"
TOOL_VERSION = "vcs script version : X-2025.06"
FILELIST = "+define+SIMULATION\nhw/sys/sep/rtl/sep.sv\n"


def fingerprint(build_args: list[str], extra: list[str] | None = None) -> str:
    return build_fingerprint(
        build_args=build_args,
        top_module=TOP,
        tool_version=TOOL_VERSION,
        filelist_text=FILELIST,
        extra=extra or [],
    )


class FingerprintJobCountTest(unittest.TestCase):
    """The compile job count names how fast a model builds, never which model."""

    def test_vcs_job_count_does_not_change_the_fingerprint(self) -> None:
        base = ["-sverilog", "+define+SIMULATION"]
        one = base + vcs_build_args({}, {}, 1)
        eight = base + vcs_build_args({}, {}, 8)
        self.assertIn("-j8", eight)
        self.assertNotIn("-j8", one)
        self.assertEqual(fingerprint(one), fingerprint(eight))

    def test_verilator_job_count_does_not_change_the_fingerprint(self) -> None:
        base = ["--timing"]
        four = base + option_build_args({}, {}, 4)
        sixteen = base + option_build_args({}, {}, 16)
        self.assertEqual(four[-2:], ["--build-jobs", "4"])
        self.assertEqual(fingerprint(four), fingerprint(sixteen))

    def test_xcelium_thread_count_does_not_change_the_fingerprint(self) -> None:
        two = xcelium_build_args({}, {"mce": True}, 2)
        eight = xcelium_build_args({}, {"mce": True}, 8)
        self.assertIn("-mce_build_thread_count", two)
        self.assertEqual(fingerprint(two), fingerprint(eight))

    def test_configured_build_jobs_do_not_change_the_fingerprint(self) -> None:
        configured = vcs_build_args({"build_jobs": 12}, {}, 1)
        command_line = vcs_build_args({}, {}, 3)
        self.assertEqual(fingerprint(configured), fingerprint(command_line))

    def test_other_arguments_still_change_the_fingerprint(self) -> None:
        plain = ["-sverilog", "-j8"]
        self.assertNotEqual(fingerprint(plain), fingerprint(plain + ["+define+RANDOM=0"]))
        self.assertNotEqual(fingerprint(plain), fingerprint(plain + ["-partcomp"]))
        self.assertNotEqual(fingerprint(plain), fingerprint(plain, extra=["target:default"]))

    def test_only_the_job_count_tokens_are_dropped(self) -> None:
        args = [
            "-j8",
            "-sverilog",
            "--build-jobs",
            "4",
            "-mce_build_thread_count",
            "2",
            "-CFLAGS",
            "-O0",
            "-jN",
            "-partcomp=autopart_low",
        ]
        self.assertEqual(
            fingerprint_build_args(args),
            ["-sverilog", "-CFLAGS", "-O0", "-jN", "-partcomp=autopart_low"],
        )


if __name__ == "__main__":
    unittest.main()
