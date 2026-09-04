# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for single-target coverage merge input validation and argv rendering.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.coverage import (  # noqa: E402
    CoverageCompatibilityError,
    discover_coverage_inputs,
    new_manifest,
    render_tokens,
)


def _leaf(
    run_dir: Path,
    item: str,
    seed: int,
    target: str,
    fingerprint: str | None,
    *,
    tool: str = "vcs",
) -> None:
    """Write one leaf result.json plus a non-empty coverage artifact beside it."""
    leaf = run_dir / item / f"seed_{seed}"
    artifact = leaf / "coverage" / "simv.vdb"
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "db").write_text("x", encoding="utf-8")
    payload = {
        "flow": "sep",
        "tool": tool,
        "item": item,
        "seed": seed,
        "status": "PASS",
        "artifacts": {"coverage": str(artifact)},
        "target": target,
        "target_build": {"target": target, "fingerprint": fingerprint},
    }
    (leaf / "result.json").write_text(json.dumps(payload), encoding="utf-8")


class MergeCompatibilityTest(unittest.TestCase):
    def _discover(self, run_dir: Path):
        return discover_coverage_inputs(
            root=run_dir,
            run_dir=run_dir,
            flow="sep",
            tool="vcs",
            fallback_glob="**/coverage/simv.vdb",
        )

    def test_two_targets_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _leaf(run_dir, "sep_axi_smoke_test", 1, "lsu_stub_all_live", "aaa")
            _leaf(run_dir, "sep_hello_world_test", 1, "default", "bbb")
            with self.assertRaises(CoverageCompatibilityError) as ctx:
                self._discover(run_dir)
            self.assertIn("incompatible targets", str(ctx.exception))

    def test_stale_build_within_one_target_refused(self) -> None:
        """Two builds of the same target still cannot be merged."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _leaf(run_dir, "sep_axi_smoke_test", 1, "default", "fresh")
            _leaf(run_dir, "sep_address_map_test", 1, "default", "stale")
            with self.assertRaises(CoverageCompatibilityError) as ctx:
                self._discover(run_dir)
            self.assertIn("build fingerprints", str(ctx.exception))

    def test_missing_fingerprint_within_target_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _leaf(run_dir, "sep_axi_smoke_test", 1, "default", "aaa")
            _leaf(run_dir, "sep_address_map_test", 1, "default", None)
            with self.assertRaises(CoverageCompatibilityError) as ctx:
                self._discover(run_dir)
            self.assertIn("incomplete", str(ctx.exception))

    def test_missing_target_provenance_refused(self) -> None:
        """An input with no target cannot be attributed to a group."""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _leaf(run_dir, "sep_axi_smoke_test", 1, "default", "aaa")
            _leaf(run_dir, "sep_address_map_test", 1, "", "aaa")
            with self.assertRaises(CoverageCompatibilityError) as ctx:
                self._discover(run_dir)
            self.assertIn("target provenance is incomplete", str(ctx.exception))

    def test_manifest_single_target_keeps_scalar_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _leaf(run_dir, "sep_axi_smoke_test", 1, "default", "aaa")
            manifest = new_manifest(
                flow="sep",
                tool="vcs",
                parser="urg",
                supported_metrics=["line"],
                discovery=self._discover(run_dir),
                merged=run_dir / "cov" / "merged.vdb",
                root=run_dir,
                exclude_files=[],
                waiver_files=[],
            )
            self.assertEqual(manifest["target"], "default")
            self.assertEqual(manifest["build_fingerprint"], "aaa")


class RenderTokensTest(unittest.TestCase):
    TEMPLATE = [
        "urg",
        "-full64",
        "-dir",
        "{design_db}",
        "-dir",
        "{inputs}",
        "-dbname",
        "{merged}",
    ]

    def test_design_db_falls_back_to_context(self) -> None:
        """Without a design_dbs list the token stays single-valued."""
        argv = render_tokens(
            self.TEMPLATE,
            {"design_db": "/cpu/cov_build.vdb", "merged": "/cov/merged.vdb"},
            ["/a/simv.vdb"],
        )
        self.assertEqual(argv[:5], ["urg", "-full64", "-dir", "/cpu/cov_build.vdb", "-dir"])
        self.assertIn("/a/simv.vdb", argv)


if __name__ == "__main__":
    unittest.main()
