# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Self-tests for the --dft-ignore-error rewrite of randomize_efuse.py."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPT = _HERE / "randomize_efuse.py"
_DEFAULT = _HERE / "configurations" / "default_efuse.toml"

DFT_IGNORE_ERROR = 1 << 15
# Every other assigned SMC_CONFIG bit, so a rewrite that touches more than bit 15 shows.
OTHER_BITS = 0x0000_7FFF | 0xFFFF_0000


def _with_smc_config(value: int) -> str:
    text = _DEFAULT.read_text()
    header = "[SMC_CONFIG.fields.smc_config]"
    head, tail = text.split(header, 1)
    tail = re.sub(r"value\s*=\s*\S+", f"value = {value:#x}", tail, count=1)
    return head + header + tail


class RandomizeEfuseDftIgnoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, base_value: int, *extra: str, seed: int = 7) -> tuple[dict, str]:
        base = self.tmp / "base.toml"
        base.write_text(_with_smc_config(base_value))
        out = self.tmp / "out.toml"
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), str(base), "--output_file", str(out)]
            + ["--seed", str(seed), *extra],
            check=True,
            capture_output=True,
            text=True,
        )
        return tomllib.loads(out.read_text()), result.stdout

    @staticmethod
    def _smc_config(config: dict) -> int:
        return int(config["SMC_CONFIG"]["fields"]["smc_config"]["value"])

    def test_zero_clears_only_bit_15(self) -> None:
        base = OTHER_BITS | DFT_IGNORE_ERROR
        config, _ = self._run(base, "--dft-ignore-error", "0")
        value = self._smc_config(config)
        self.assertEqual(value & DFT_IGNORE_ERROR, 0)
        self.assertEqual(value & ~DFT_IGNORE_ERROR, base & ~DFT_IGNORE_ERROR)

    def test_one_sets_only_bit_15(self) -> None:
        base = OTHER_BITS & ~DFT_IGNORE_ERROR
        config, _ = self._run(base, "--dft-ignore-error", "1")
        value = self._smc_config(config)
        self.assertNotEqual(value & DFT_IGNORE_ERROR, 0)
        self.assertEqual(value & ~DFT_IGNORE_ERROR, base & ~DFT_IGNORE_ERROR)

    def test_absent_option_keeps_the_base_value(self) -> None:
        for base in (0, OTHER_BITS | DFT_IGNORE_ERROR):
            config, _ = self._run(base)
            self.assertEqual(self._smc_config(config), base)

    def test_seeded_fields_do_not_depend_on_the_option(self) -> None:
        plain, plain_out = self._run(0, "--i2c-ids")
        forced, forced_out = self._run(0, "--i2c-ids", "--dft-ignore-error", "1")
        for block, fld in (
            ("OCCP_TRANSPORT_TIMEOUT", "transport_timeout"),
            ("I2C_I3C_ID", "interface_id"),
        ):
            self.assertEqual(
                plain[block]["fields"][fld]["value"], forced[block]["fields"][fld]["value"]
            )
        self.assertIn("I2C_I3C_ID[6]=", plain_out)
        self.assertIn("SMC_CONFIG.dft_ignore_error=1", forced_out)

    def test_values_other_than_zero_and_one_are_rejected(self) -> None:
        base = self.tmp / "base.toml"
        base.write_text(_DEFAULT.read_text())
        for bad in ("2", "-1"):
            result = subprocess.run(
                [sys.executable, str(_SCRIPT), str(base), "--output_file", str(self.tmp / "o")]
                + ["--seed", "1", "--dft-ignore-error", bad],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
