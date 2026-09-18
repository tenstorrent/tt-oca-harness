# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "tools/regs/reggen_wrapper.py"
KMAC_HJSON = ROOT / "vendor/lowRISC/opentitan/upstream/hw/ip/kmac/data/kmac.hjson"


class ReggenWrapperTest(unittest.TestCase):
    def test_legacy_roundtrip_dialect(self):
        with TemporaryDirectory() as temp:
            output = Path(temp) / "kmac.rdl"
            result = subprocess.run(
                [
                    sys.executable,
                    str(WRAPPER),
                    "--systemrdl",
                    "-o",
                    str(output),
                    str(KMAC_HJSON),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rdl = output.read_text()

        self.assertIn("} kmac_en[0:0]", rdl)
        self.assertIn("} PREFIX[11] @ 0xB4 += 0x4;", rdl)
        self.assertNotIn("PREFIX_0[", rdl)
        self.assertIn("mementries = 0x200;", rdl)
        self.assertIn('name = "KMAC Accelerator"', rdl)
        self.assertTrue(rdl.startswith("`ifndef _KMAC_RDL_DEFINED\n"))
        self.assertIn('`include "opentitan_udps.rdl"', rdl)


if __name__ == "__main__":
    unittest.main()
