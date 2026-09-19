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
AES_HJSON = ROOT / "vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson"
CSRNG_HJSON = ROOT / "vendor/lowRISC/opentitan/upstream/hw/ip/csrng/data/csrng.hjson"


class ReggenWrapperTest(unittest.TestCase):
    def _export(self, hjson: Path, *options: str) -> str:
        with TemporaryDirectory() as temp:
            output = Path(temp) / "registers.rdl"
            result = subprocess.run(
                [
                    sys.executable,
                    str(WRAPPER),
                    "--systemrdl",
                    *options,
                    "-o",
                    str(output),
                    str(hjson),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return output.read_text()

    def test_legacy_roundtrip_dialect(self):
        rdl = self._export(KMAC_HJSON)

        self.assertIn("} kmac_en[0:0]", rdl)
        self.assertIn("} PREFIX[11] @ 0xB4 += 0x4;", rdl)
        self.assertNotIn("PREFIX_0[", rdl)
        self.assertIn("mementries = 0x200;", rdl)
        self.assertIn('name = "KMAC Accelerator"', rdl)
        self.assertTrue(rdl.startswith("`ifndef _KMAC_RDL_DEFINED\n"))
        self.assertIn('`include "opentitan_udps.rdl"', rdl)

    def test_base_multireg_field_name(self):
        rdl = self._export(
            AES_HJSON,
            "--uppercase-fields",
            "--base-multireg-fields",
        )
        self.assertIn("} KEY_SHARE0[31:0]", rdl)
        self.assertNotIn("} KEY_SHARE0_0[31:0]", rdl)

    def test_flatten_multiregs(self):
        rdl = self._export(
            CSRNG_HJSON,
            "--uppercase-fields",
            "--flatten-multiregs",
        )
        self.assertIn("} external RESEED_COUNTER_0 @ 0x20;", rdl)
        self.assertIn("} external RESEED_COUNTER_1 @ 0x24;", rdl)
        self.assertIn("} external RESEED_COUNTER_2 @ 0x28;", rdl)
        self.assertEqual(rdl.count("} RESEED_COUNTER_0[31:0]"), 3)
        self.assertNotIn("RESEED_COUNTER[3]", rdl)


if __name__ == "__main__":
    unittest.main()
