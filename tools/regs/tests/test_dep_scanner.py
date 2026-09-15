# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCANNER = Path(__file__).resolve().parents[1] / "dep_scanner.py"


class DepScannerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.top = self.root / "top.rdl"
        self.fragment = self.root / "fragment.rdl"
        self.fragment.write_text("reg value_t { field {} value[31:0]; };\n")
        self.top.write_text('`include "fragment.rdl"\naddrmap top { value_t value; };\n')
        (self.root / "udp.rdl").write_text("")
        scan = shlex.join(
            [
                sys.executable,
                str(SCANNER),
                "-u",
                "udp.rdl",
                "top.rdl",
                "--target",
                "output",
                "-o",
                "deps.d",
            ]
        )
        (self.root / "Makefile").write_text(
            "all: output\n"
            "output: top.rdl udp.rdl\n\ttouch $@\n"
            f"{self.root}/deps.d: top.rdl udp.rdl {SCANNER}\n\t{scan}\n"
            f"-include {self.root}/deps.d\n"
        )
        self.make()

    def make(self):
        result = subprocess.run(
            ["make", "--no-print-directory"],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_relocated_include(self):
        self.fragment.rename(self.root / "moved.rdl")
        self.top.write_text(self.top.read_text().replace("fragment.rdl", "moved.rdl"))
        self.make()
        deps = (self.root / "deps.d").read_text()
        self.assertIn("moved.rdl", deps)
        self.assertNotIn("fragment.rdl", deps)
        self.assertNotIn("touch output", self.make())

    def test_removed_include(self):
        self.top.write_text(self.fragment.read_text() + "addrmap top { value_t value; };\n")
        self.fragment.unlink()
        self.make()
        self.assertNotIn("fragment.rdl", (self.root / "deps.d").read_text())

    def test_include_only_change_rebuilds_output(self):
        output = self.root / "output"
        self.fragment.write_text(self.fragment.read_text().replace("31:0", "15:0"))
        os.utime(output, (1, 1))
        os.utime(self.root / "deps.d", (1, 1))
        self.assertIn("touch output", self.make())
        self.assertNotIn("touch output", self.make())

    def test_unresolved_include_is_rejected(self):
        before = (self.root / "deps.d").read_bytes()
        self.fragment.unlink()
        result = subprocess.run(
            [sys.executable, str(SCANNER), "-u", "udp.rdl", "top.rdl", "-o", "deps.d"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "deps.d").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
