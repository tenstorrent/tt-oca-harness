# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for coverage merge input selection and the merge manifest.

The `cov_merge` stage merges the final non-debug attempt of every leaf that wrote a
database, whatever the leaf's status, refuses inputs of mixed provenance, and records every
selection and rejection in `cov/coverage.json`.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.coverage import (  # noqa: E402
    CoverageCompatibilityError,
    CoverageInput,
    _validate_compatibility,
    discover_coverage_inputs,
    new_manifest,
)
from runlib.coverage_closure import coverage_fail_under  # noqa: E402
from runlib.models import ConfigError  # noqa: E402

FLOW = "fixture"
TOOL = "verilator"
GLOB = "**/coverage/coverage.dat"
MANIFEST_FIELDS = {
    "schema_version",
    "generated_at",
    "dut",
    "tool",
    "parser",
    "status",
    "supported_metrics",
    "target",
    "build_fingerprint",
    "selection_policy",
    "selection_source",
    "inputs",
    "rejected",
    "exclusions",
    "waivers",
    "artifacts",
}


def provenance(target="t1", fingerprint="fp1"):
    return CoverageInput(
        path=f"run/{target}/{fingerprint}/coverage.dat",
        item="t",
        seed=1,
        attempt=0,
        status="PASS",
        target=target,
        build_fingerprint=fingerprint,
        result_json="run/result.json",
        source="result_json",
    )


class RunTree(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()

    def leaf(
        self,
        item,
        seed,
        attempt=0,
        status="PASS",
        *,
        database=True,
        debug_only=False,
        target="t1",
        fingerprint="fp1",
        flow=FLOW,
        tool=TOOL,
    ):
        leaf_dir = self.run_dir / item / f"seed_{seed}" / f"attempt_{attempt}"
        (leaf_dir / "coverage").mkdir(parents=True)
        database_path = leaf_dir / "coverage" / "coverage.dat"
        if database:
            database_path.write_text("C 'point' 1\n")
        record = {
            "item": item,
            "seed": seed,
            "attempt": attempt,
            "status": status,
            "flow": flow,
            "tool": tool,
            "artifacts": {"coverage": str(database_path.relative_to(self.root))},
            "metadata": {"debug_only": True} if debug_only else {},
        }
        if target or fingerprint:
            record["target_build"] = {"target": target, "fingerprint": fingerprint}
        (leaf_dir / "result.json").write_text(json.dumps(record))
        return str(database_path.relative_to(self.root))

    def discover(self):
        return discover_coverage_inputs(
            root=self.root, run_dir=self.run_dir, flow=FLOW, tool=TOOL, fallback_glob=GLOB
        )

    def test_the_final_attempt_of_every_test_and_seed_is_selected(self):
        first = self.leaf("t_a", 1, attempt=0, status="FAIL")
        retry = self.leaf("t_a", 1, attempt=1, status="PASS")
        other_seed = self.leaf("t_a", 2)
        other_test = self.leaf("t_b", 1)
        discovery = self.discover()
        self.assertEqual(discovery.selection_source, "result_json")
        self.assertEqual(
            sorted(entry.path for entry in discovery.inputs),
            sorted([retry, other_seed, other_test]),
        )
        self.assertEqual(
            [(entry["path"], entry["reason"]) for entry in discovery.rejected],
            [(first, "superseded retry attempt")],
        )

    def test_leaf_status_is_recorded_and_never_filters(self):
        self.leaf("t_pass", 1, status="PASS")
        self.leaf("t_fail", 1, status="FAIL")
        self.leaf("t_timeout", 1, status="TIMEOUT")
        statuses = {entry.item: entry.status for entry in self.discover().inputs}
        self.assertEqual(statuses, {"t_pass": "PASS", "t_fail": "FAIL", "t_timeout": "TIMEOUT"})

    def test_debug_reruns_and_missing_databases_are_rejected(self):
        kept = self.leaf("t_a", 1)
        self.leaf("t_debug", 1, debug_only=True)
        missing = self.leaf("t_empty", 1, database=False)
        discovery = self.discover()
        self.assertEqual([entry.path for entry in discovery.inputs], [kept])
        reasons = sorted(entry["reason"] for entry in discovery.rejected)
        self.assertEqual(reasons, ["coverage artifact missing or empty", "debug-only rerun"])
        self.assertIn(missing, [entry.get("path") for entry in discovery.rejected])

    def test_a_fragment_of_another_flow_or_tool_is_refused(self):
        self.leaf("t_a", 1)
        self.leaf("t_b", 1, flow="other")
        with self.assertRaisesRegex(CoverageCompatibilityError, "belongs to other/verilator"):
            self.discover()

    def test_mixed_targets_or_build_fingerprints_are_refused(self):
        self.leaf("t_a", 1, target="t1")
        self.leaf("t_b", 1, target="t2")
        with self.assertRaisesRegex(CoverageCompatibilityError, "incompatible targets"):
            self.discover()
        shutil.rmtree(self.run_dir / "t_b")
        self.leaf("t_c", 1, fingerprint="fp2")
        with self.assertRaisesRegex(CoverageCompatibilityError, "incompatible build fingerprints"):
            self.discover()

    def test_provenance_free_inputs_merge_as_one_set(self):
        self.leaf("t_a", 1, target=None, fingerprint=None)
        self.leaf("t_b", 1, target=None, fingerprint=None)
        discovery = self.discover()
        self.assertEqual(len(discovery.inputs), 2)
        self.assertEqual({entry.target for entry in discovery.inputs}, {None})

    def test_leaf_records_are_the_authority_over_the_glob(self):
        self.leaf("t_a", 1)
        stray = self.run_dir / "stray" / "coverage" / "coverage.dat"
        stray.parent.mkdir(parents=True)
        stray.write_text("C 'point' 1\n")
        discovery = self.discover()
        self.assertEqual([entry.item for entry in discovery.inputs], ["t_a"])

    def test_glob_fallback_without_leaf_records(self):
        for name in ("one", "two"):
            path = self.run_dir / name / "coverage" / "coverage.dat"
            path.parent.mkdir(parents=True)
            path.write_text("C 'point' 1\n")
        empty = self.run_dir / "three" / "coverage" / "coverage.dat"
        empty.parent.mkdir(parents=True)
        empty.write_text("")
        discovery = self.discover()
        self.assertEqual(discovery.selection_source, "legacy_glob")
        self.assertEqual(len(discovery.inputs), 2)
        self.assertEqual({entry.status for entry in discovery.inputs}, {"UNKNOWN"})
        self.assertEqual({entry.item for entry in discovery.inputs}, {None})

    def test_manifest_records_the_selection_and_the_rejections(self):
        self.leaf("t_a", 1, attempt=0, status="FAIL")
        self.leaf("t_a", 1, attempt=1)
        discovery = self.discover()
        manifest = new_manifest(
            flow=FLOW,
            tool=TOOL,
            parser="verilator_coverage",
            supported_metrics=["line", "branch"],
            discovery=discovery,
            merged=self.run_dir / "cov" / "merged.dat",
            root=self.root,
            exclude_files=["cov/exclude.vlt"],
        )
        self.assertEqual(set(manifest), MANIFEST_FIELDS)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["status"], "PENDING")
        self.assertEqual(manifest["selection_policy"], "final_non_debug_attempt_per_test_seed")
        self.assertEqual(manifest["selection_source"], "result_json")
        self.assertEqual((manifest["target"], manifest["build_fingerprint"]), ("t1", "fp1"))
        self.assertEqual([entry["attempt"] for entry in manifest["inputs"]], [1])
        self.assertEqual(
            [entry["reason"] for entry in manifest["rejected"]], ["superseded retry attempt"]
        )
        self.assertEqual(manifest["exclusions"], ["cov/exclude.vlt"])
        self.assertEqual(manifest["waivers"], [])
        self.assertEqual(
            manifest["artifacts"], {"merged": "run/cov/merged.dat", "report": None, "summary": None}
        )


class Compatibility(unittest.TestCase):
    def test_one_target_and_one_fingerprint(self):
        _validate_compatibility([provenance(), provenance()])
        _validate_compatibility([provenance(None, None), provenance(None, None)])

    def test_incomplete_provenance_is_refused_beside_complete_inputs(self):
        with self.assertRaisesRegex(CoverageCompatibilityError, "target provenance is incomplete"):
            _validate_compatibility([provenance(), provenance(target=None)])
        with self.assertRaisesRegex(CoverageCompatibilityError, "fingerprints are incomplete"):
            _validate_compatibility([provenance(), provenance(fingerprint=None)])


class CompatibilityThreshold(unittest.TestCase):
    def test_tool_fail_under_parses_or_is_absent(self):
        self.assertIsNone(coverage_fail_under(TOOL, {}))
        self.assertIsNone(coverage_fail_under(TOOL, {"fail_under": ""}))
        self.assertEqual(coverage_fail_under(TOOL, {"fail_under": 75}), 75.0)
        self.assertEqual(coverage_fail_under(TOOL, {"fail_under": "98"}), 98.0)
        with self.assertRaisesRegex(ConfigError, "fail_under. must be a number"):
            coverage_fail_under(TOOL, {"fail_under": "most"})


if __name__ == "__main__":
    unittest.main()
