# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Self-tests of the one-cell artifact writer and the closure merge.

Run from the repository root:
    python3 -m unittest hw/sys/sep/dv/cocotb/env/test_sep_rom_functional_coverage.py
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sep_rom_functional_coverage as fcov  # noqa: E402

FEATURE = "SEP-ROM-SECONDARY-SECURE"
REQUIRED = sorted(
    f"lc={lc},image={image}"
    for lc in ("prod", "prod_end")
    for image in ("signed", "unsigned", "corrupt_signature")
)


class FeatureCellTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _leaf(self, seed: int, cell: str, required=REQUIRED, status: str | None = None) -> Path:
        attempt = self.run_dir / f"leaf@rom_boot/seed_{seed}/attempt_0"
        path = fcov.write_feature_cell(
            FEATURE, required, cell, {"seed_note": seed}, seed=seed, out_dir=attempt / "results"
        )
        if status is not None:
            (attempt / "result.json").write_text(json.dumps({"status": status, "seed": seed}))
        return path

    def _main(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = fcov.main(["merge", str(self.run_dir), "--feature", FEATURE, *extra])
        return rc, out.getvalue()

    def _merged(self) -> dict:
        return json.loads((self.run_dir / f"functional-coverage-merge-{FEATURE}.json").read_text())

    def test_artifact_holds_exactly_one_cell(self) -> None:
        path = self._leaf(7, REQUIRED[0])
        report = json.loads(path.read_text())
        self.assertEqual(path.name, fcov.REPORT_NAME)
        self.assertEqual(set(report), set(fcov._KEYS))
        self.assertEqual(report["feature_key"], FEATURE)
        self.assertEqual(report["seed"], 7)
        self.assertEqual(report["required_cells"], REQUIRED)
        self.assertEqual(report["cells_hit"], [REQUIRED[0]])
        self.assertEqual(report["measurements"], {"seed_note": 7})
        self.assertIs(report["satisfied"], False)

    def test_single_required_cell_artifact_is_satisfied_alone(self) -> None:
        path = self._leaf(1, "only", required=["only"])
        self.assertIs(json.loads(path.read_text())["satisfied"], True)

    def test_writer_rejects_cell_outside_required(self) -> None:
        with self.assertRaises(ValueError):
            fcov.write_feature_cell(
                FEATURE, REQUIRED, "lc=test_dev,image=signed", {}, seed=1, out_dir=self.run_dir
            )
        self.assertFalse((self.run_dir / fcov.REPORT_NAME).exists())

    def test_writer_rejects_more_than_one_cell(self) -> None:
        with self.assertRaises(ValueError):
            fcov.write_feature_cell(
                FEATURE, REQUIRED, REQUIRED[:2], {}, seed=1, out_dir=self.run_dir
            )
        self.assertFalse((self.run_dir / fcov.REPORT_NAME).exists())

    def test_writer_defaults_to_the_cocotb_results_directory(self) -> None:
        results = self.run_dir / "attempt_0" / "results"
        results.mkdir(parents=True)
        env = {"COCOTB_RESULTS_FILE": str(results / "results.xml")}
        with mock.patch.dict(os.environ, env):
            path = fcov.write_feature_cell(FEATURE, REQUIRED, REQUIRED[1], {}, seed=3)
        self.assertEqual(path, results.resolve() / fcov.REPORT_NAME)

    def test_merge_unions_cells_across_artifacts(self) -> None:
        self._leaf(1, REQUIRED[0])
        self._leaf(2, REQUIRED[3])
        self._leaf(3, REQUIRED[3])
        merged = fcov.merge(self.run_dir, FEATURE)
        self.assertEqual(merged["cells_hit"], sorted({REQUIRED[0], REQUIRED[3]}))
        self.assertEqual(merged["hit_counts"][REQUIRED[3]], 2)
        self.assertEqual(len(merged["artifacts"]), 3)

    def test_missing_cell_exits_nonzero(self) -> None:
        for seed, cell in enumerate(REQUIRED[:-1], start=1):
            self._leaf(seed, cell)
        rc, out = self._main()
        self.assertEqual(rc, 1)
        self.assertIn(f"missing  : {REQUIRED[-1]}", out)
        self.assertIn("satisfied: false", out)
        merged = self._merged()
        self.assertEqual(merged["missing_cells"], [REQUIRED[-1]])
        self.assertIs(merged["satisfied"], False)

    def test_all_six_cells_satisfy(self) -> None:
        for seed, cell in enumerate(REQUIRED, start=1):
            self._leaf(seed, cell, status="PASS")
        rc, out = self._main()
        self.assertEqual(rc, 0, out)
        self.assertIn("satisfied: true", out)
        merged = self._merged()
        self.assertEqual(merged["cells_hit"], REQUIRED)
        self.assertEqual(merged["missing_cells"], [])
        self.assertIs(merged["satisfied"], True)

    def test_mismatched_required_sets_fail(self) -> None:
        for seed, cell in enumerate(REQUIRED, start=1):
            self._leaf(seed, cell)
        self._leaf(99, REQUIRED[0], required=REQUIRED[:3])
        rc, out = self._main()
        self.assertEqual(rc, 1)
        self.assertIn("disagree on required_cells", out)

    def test_no_artifact_fails(self) -> None:
        rc, out = self._main()
        self.assertEqual(rc, 1)
        self.assertIn("no functional-coverage-report.json", out)

    def test_other_feature_is_not_counted(self) -> None:
        fcov.write_feature_cell("OTHER", ["x"], "x", {}, seed=1, out_dir=self.run_dir / "o")
        rc, out = self._main()
        self.assertEqual(rc, 1)
        self.assertIn("no functional-coverage-report.json", out)

    def test_artifact_with_two_hits_fails(self) -> None:
        for seed, cell in enumerate(REQUIRED, start=1):
            self._leaf(seed, cell)
        path = self._leaf(50, REQUIRED[0])
        report = json.loads(path.read_text())
        report["cells_hit"] = REQUIRED[:2]
        path.write_text(json.dumps(report))
        rc, out = self._main()
        self.assertEqual(rc, 1)
        self.assertIn("exactly one cell", out)

    def test_hit_from_failed_leaf_fails(self) -> None:
        for seed, cell in enumerate(REQUIRED, start=1):
            self._leaf(seed, cell, status="PASS")
        self._leaf(60, REQUIRED[0], status="FAIL")
        rc, out = self._main()
        self.assertEqual(rc, 1)
        self.assertIn("a failing leaf must not write a hit", out)

    def test_cli_exit_code(self) -> None:
        for seed, cell in enumerate(REQUIRED[1:], start=1):
            self._leaf(seed, cell)
        cmd = [sys.executable, fcov.__file__, "merge", str(self.run_dir), "--feature", FEATURE]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn(f"missing  : {REQUIRED[0]}", proc.stdout)
        self._leaf(10, REQUIRED[0])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
