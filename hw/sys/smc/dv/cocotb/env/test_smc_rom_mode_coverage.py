# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Self-tests for the four-cell boot-mode merge in smc_rom_mode_coverage.py."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smc_rom_mode_coverage as cov  # noqa: E402

LEAF = "smc_occp_boot_sequence_status_test@dual"


class ModeCoverageMergeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "20261107_000000__verilator__multi"
        self.run_dir.mkdir()
        self.runs: list[dict] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _add_run(
        self, seed: int, primary: bool, recovery: bool, status: str = "PASS", write: bool = True
    ) -> None:
        attempt = self.run_dir / LEAF / f"seed_{seed}" / "attempt_0"
        (attempt / "results").mkdir(parents=True)
        if write:
            cov.write_leaf_artifact(
                attempt / cov.ARTIFACT_NAME, seed=seed, primary=primary, recovery=recovery
            )
        xml = f"hw/sys/smc/dv/build/runs/{self.run_dir.name}/{LEAF}/seed_{seed}/attempt_0/results/results.xml"
        self.runs.append({"seed": seed, "status": status, "artifacts": {"results_xml": xml}})
        (self.run_dir / LEAF / "result.json").write_text(
            json.dumps({"item": LEAF, "runs": self.runs})
        )

    def _cli(self) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cov.main(["merge", str(self.run_dir)])
        return code, json.loads(out.getvalue())

    def test_single_leaf_artifact_is_not_satisfied(self) -> None:
        art = cov.leaf_artifact(seed=1, primary=True, recovery=False)
        self.assertEqual(art["cells_hit"], ["primary=1,recovery=0"])
        self.assertFalse(art["satisfied"])

    def test_incomplete_union_fails(self) -> None:
        self._add_run(1, False, False)
        self._add_run(2, True, True)
        self._add_run(3, True, False)
        code, report = self._cli()
        self.assertEqual(code, 1)
        self.assertFalse(report["satisfied"])
        self.assertEqual(report["missing_cells"], ["primary=0,recovery=1"])

    def test_complete_union_passes(self) -> None:
        for seed, (p, r) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1), (1, 1)), start=1):
            self._add_run(seed, bool(p), bool(r))
        code, report = self._cli()
        self.assertEqual(code, 0)
        self.assertTrue(report["satisfied"])
        self.assertEqual(report["cells_hit"], list(cov.REQUIRED_CELLS))
        self.assertEqual(report["measurements"]["seeds_per_cell"]["primary=1,recovery=1"], [4, 5])

    def test_failed_leaf_contributes_no_cell(self) -> None:
        self._add_run(1, False, False)
        self._add_run(2, False, True, status="FAIL")
        self._add_run(3, True, False)
        self._add_run(4, True, True)
        code, report = self._cli()
        self.assertEqual(code, 1)
        self.assertEqual(report["missing_cells"], ["primary=0,recovery=1"])
        self.assertEqual(report["measurements"]["excluded"][0]["seed"], 2)

    def test_seed_mismatch_is_rejected(self) -> None:
        self._add_run(7, True, True)
        art = self.run_dir / LEAF / "seed_7" / "attempt_0" / cov.ARTIFACT_NAME
        data = json.loads(art.read_text())
        data["seed"] = 8
        art.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            cov.merge(self.run_dir)

    def test_malformed_artifact_is_rejected(self) -> None:
        self._add_run(1, True, True)
        art = self.run_dir / LEAF / "seed_1" / "attempt_0" / cov.ARTIFACT_NAME
        data = json.loads(art.read_text())
        data["cells_hit"] = list(cov.REQUIRED_CELLS)
        art.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            cov.merge(self.run_dir)

    def test_empty_run_dir_is_not_satisfied(self) -> None:
        code, report = self._cli()
        self.assertEqual(code, 1)
        self.assertEqual(report["missing_cells"], list(cov.REQUIRED_CELLS))


if __name__ == "__main__":
    unittest.main()
