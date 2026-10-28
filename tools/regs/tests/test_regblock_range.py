# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]

# 0x4 is a gap; the block ends at 0xC.
RDL = """
addrmap gappy {
    reg { field { sw = rw; hw = r; } f[31:0] = 0; } A @ 0x0;
    reg { field { sw = rw; hw = r; } f[31:0] = 0; } B @ 0x8;
};
"""


def export(tmp: Path, *options: str) -> subprocess.CompletedProcess:
    cfg = tmp / "peakrdl.toml"
    cfg.write_text(
        f'[peakrdl]\npython_search_paths = ["{ROOT / "tools/regs"}"]\n'
        '[peakrdl.plugins.exporters]\nregblock-range = "regblock_range:Exporter"\n'
    )
    rdl = tmp / "gappy.rdl"
    rdl.write_text(RDL)
    return subprocess.run(
        [sys.executable, "-m", "peakrdl", "--peakrdl-cfg", str(cfg), "regblock-range",
         str(rdl), "-o", str(tmp / "out"), "--cpuif", "axi4-lite-flat", *options],
        capture_output=True,
        text=True,
        timeout=120,
    )


def decode(tmp: Path) -> str:
    module = (tmp / "out/gappy.sv").read_text()
    return re.search(r"automatic logic is_valid_addr;.*?\n    end\n", module, re.S).group(0)


class RegblockRangeTest(unittest.TestCase):
    def test_range_check_replaces_per_register_hits(self) -> None:
        with TemporaryDirectory() as tmp:
            result = export(Path(tmp), "--err-if-out-of-range")
            self.assertEqual(result.returncode, 0, result.stderr)
            body = decode(Path(tmp))
            self.assertRegex(
                body,
                r"is_valid_addr \|= [^\n]*\n\s*is_valid_addr = cpuif_addr < 4'hc;\n"
                r"\s*decoded_err = ~is_valid_addr & decoded_req;",
            )

    def test_wider_port_compares_at_its_width(self) -> None:
        with TemporaryDirectory() as tmp:
            result = export(Path(tmp), "--err-if-out-of-range", "--addr-width", "12")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("is_valid_addr = cpuif_addr < 12'hc;", decode(Path(tmp)))

    def test_without_option_is_stock_regblock(self) -> None:
        with TemporaryDirectory() as tmp:
            result = export(Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            body = decode(Path(tmp))
            self.assertIn("decoded_err = '0;", body)
            self.assertNotIn("cpuif_addr <", body)

    def test_rejects_stock_error_checks(self) -> None:
        with TemporaryDirectory() as tmp:
            result = export(Path(tmp), "--err-if-out-of-range", "--err-if-bad-addr")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--err-if-out-of-range excludes", result.stderr)


if __name__ == "__main__":
    unittest.main()
