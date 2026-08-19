# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Regression coverage for collecting relocated native run artifacts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
DV_TOOLS = REPO_ROOT / "tools" / "dv"
sys.path.insert(0, str(DV_TOOLS))

from dashboard import collect_results  # noqa: E402
from runlib.models import Flow, TestCatalog, TestEntry  # noqa: E402


def fixture_flow() -> Flow:
    return Flow(
        name="fixture",
        kind="dv",
        description="relocated collector fixture",
        framework="cocotb",
        visibility="public",
        runnability="open",
        license="none",
        root=".",
        default_tool="verilator",
        tools=["verilator"],
        path=REPO_ROOT / "fixture_sim_cfg.toml",
        raw={},
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


def fixture_catalog() -> TestCatalog:
    test = TestEntry(
        name="fixture_test",
        module="fixture_test",
        tags=["smoke"],
    )
    return TestCatalog(
        path=REPO_ROOT / "fixture_testlist.toml",
        tests={test.name: test},
        groups={"smoke": [test.name]},
    )


class RelocatedArtifactCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        scratch = os.environ.get("TMPDIR")
        scratch_dir = scratch if scratch and Path(scratch).is_dir() else None
        self.temporary = tempfile.TemporaryDirectory(
            prefix="ocah-collector-",
            dir=scratch_dir,
        )
        self.addCleanup(self.temporary.cleanup)
        self.run_root = Path(self.temporary.name) / "nightly-run"
        self.run_root.mkdir()

    def write_json(self, relative: Path, payload: dict[str, object]) -> Path:
        path = self.run_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def test_explicit_download_root_rebases_recorded_artifacts(self) -> None:
        recorded_root = Path("build/ci/runs/fixture/verilator/nightly/12345")
        leaf_dir = Path("fixture_test/seed_7/attempt_0")
        recorded_leaf = recorded_root / leaf_dir
        recorded_result = recorded_leaf / "result.json"
        recorded_log = recorded_leaf / "logs/fixture_test.log"
        recorded_parser_xml = recorded_leaf / "parser/guessed.xml"
        worker_root = Path("/home/runner/work/tt-oca-harness/tt-oca-harness")
        recorded_artifact_xml = worker_root / recorded_leaf / "structured/canonical.xml"

        actual_log = self.run_root / leaf_dir / "logs/fixture_test.log"
        actual_log.parent.mkdir(parents=True)
        actual_log.write_text("fixture passed\n", encoding="utf-8")
        actual_xml = self.run_root / leaf_dir / "structured/canonical.xml"
        actual_xml.parent.mkdir(parents=True)
        actual_xml.write_text(
            '<testsuites tests="1" failures="0" errors="0"/>\n',
            encoding="utf-8",
        )
        (self.run_root / "dashboard").mkdir()

        leaf_payload = {
            "schema_version": 1,
            "flow": "fixture",
            "kind": "dv",
            "framework": "cocotb",
            "tool": "verilator",
            "item": "fixture_test",
            "seed": 7,
            "attempt": 0,
            "status": "PASS",
            "return_code": 0,
            "duration_sec": 1.25,
            "run_dir": str(recorded_root),
            "log": str(recorded_log),
            "artifacts": {
                "results_xml": str(recorded_artifact_xml),
                "script": str(recorded_leaf / "scripts/sim.fixture_test.sh"),
                "backend": "dashboard",
            },
            "parser": {
                "policy": "cocotb-default",
                "status_source": "structured_result",
                "evidence": [
                    {
                        "kind": "results_xml",
                        "path": str(recorded_parser_xml),
                        "status": "PASS",
                    }
                ],
            },
        }
        actual_leaf_result = self.write_json(
            leaf_dir / "result.json",
            leaf_payload,
        )

        job = {
            "stage": "sim",
            "item": "fixture_test",
            "seed": 7,
            "attempt": 0,
            "status": "PASS",
            "duration_sec": 1.25,
            "log": str(recorded_log),
            "result_json": str(recorded_result),
            "artifacts": {
                "results_xml": str(recorded_leaf / "structured/canonical.xml")
            },
        }
        actual_regression = self.write_json(
            Path("stages/regress/regression.json"),
            {
                "schema_version": 1,
                "flow": "fixture",
                "framework": "cocotb",
                "tool": "verilator",
                "status": "PASS",
                "run_dir": str(recorded_root),
                "artifacts": {
                    "regression_json": str(
                        recorded_root / "stages/regress/regression.json"
                    )
                },
                "jobs": [job],
                "failure_buckets": [],
            },
        )
        self.write_json(
            Path("result.json"),
            {
                "schema_version": 1,
                "flow": "fixture",
                "kind": "dv",
                "framework": "cocotb",
                "tool": "verilator",
                "status": "PASS",
                "run_dir": str(recorded_root),
                "tests": {
                    "total": 1,
                    "passing": 1,
                    "failing": 0,
                    "skipped": 0,
                },
                "coverage": {"enabled": False, "status": "SKIP", "metrics": {}},
                "stages": [],
            },
        )

        with mock.patch.object(
            collect_results,
            "load_test_catalog",
            return_value=fixture_catalog(),
        ):
            normalized = collect_results.collect_flow_result(
                REPO_ROOT,
                fixture_flow(),
                self.run_root,
            )

        expected_xml = str(actual_xml.resolve())
        expected_log = str(actual_log.resolve())
        expected_leaf_result = str(actual_leaf_result.resolve())
        expected_regression = str(actual_regression.resolve())
        self.assertEqual(normalized["status"], "PASS")
        self.assertEqual(normalized["source"]["collector"], "run_dv-result")
        self.assertEqual(
            normalized["run_metadata"]["run_dir"],
            str(recorded_root),
            "recorded run identity must remain stable for trend history",
        )
        self.assertEqual(
            normalized["junit_xml"],
            [
                {
                    "item": "fixture_test",
                    "seed": 7,
                    "attempt": 0,
                    "path": expected_xml,
                    "exists": True,
                }
            ],
        )
        detail = normalized["tests_detail"][0]
        self.assertEqual(detail["junit_xml"], expected_xml)
        self.assertEqual(detail["artifacts"]["results_xml"], expected_xml)
        self.assertEqual(
            detail["artifacts"]["backend"],
            "dashboard",
            "non-path artifact metadata must not be rebased",
        )
        self.assertEqual(detail["log"], expected_log)
        self.assertEqual(detail["result_json"], expected_leaf_result)
        self.assertNotEqual(
            detail["junit_xml"],
            detail["parser"]["evidence"][0]["path"],
            "artifacts.results_xml must take precedence over parser/log guessing",
        )
        self.assertEqual(
            normalized["regression"]["artifacts"]["regression_json"],
            expected_regression,
        )
        regression_job = normalized["regression"]["jobs"][0]
        self.assertEqual(regression_job["log"], expected_log)
        self.assertEqual(regression_job["result_json"], expected_leaf_result)
        self.assertEqual(
            regression_job["artifacts"]["results_xml"],
            expected_xml,
        )
        self.assertFalse(
            any("run.json" in warning for warning in normalized.get("warnings", [])),
            f"optional run.json produced a false warning: {normalized.get('warnings')}",
        )

    def test_relative_and_absolute_recorded_paths_share_one_rebase_rule(self) -> None:
        recorded_relative = Path("build/ci/runs/fixture/verilator/nightly/12345")
        worker_root = Path("/home/runner/work/tt-oca-harness/tt-oca-harness")
        recorded_absolute = worker_root / recorded_relative
        leaf_relative = Path("fixture_test/seed_7/attempt_0/results/results.xml")
        cases = (
            (recorded_relative, recorded_relative / leaf_relative),
            (recorded_relative, recorded_absolute / leaf_relative),
            (recorded_absolute, recorded_absolute / leaf_relative),
            (recorded_absolute, recorded_relative / leaf_relative),
        )

        for recorded_root, recorded_path in cases:
            with self.subTest(
                recorded_root=str(recorded_root),
                recorded_path=str(recorded_path),
            ):
                resolved = collect_results._artifact_path(
                    REPO_ROOT,
                    self.run_root,
                    str(recorded_path),
                    recorded_root,
                )
                self.assertEqual(
                    resolved,
                    self.run_root / leaf_relative,
                    (
                        "relocated path mismatch: "
                        f"recorded_root={recorded_root} recorded_path={recorded_path} "
                        f"resolved={resolved}"
                    ),
                )

    def test_log_layout_fallback_uses_relocated_leaf(self) -> None:
        recorded_root = Path("build/ci/runs/fixture/verilator/nightly/12345")
        leaf_relative = Path("fixture_test/seed_7/attempt_0")
        actual_xml = self.run_root / leaf_relative / "results/results.xml"
        actual_xml.parent.mkdir(parents=True)
        actual_xml.write_text(
            '<testsuites tests="1" failures="0" errors="0"/>\n',
            encoding="utf-8",
        )

        guessed = collect_results._guess_junit_from_log(
            REPO_ROOT,
            self.run_root,
            str(recorded_root / leaf_relative / "logs/fixture_test.log"),
            recorded_root,
        )

        self.assertEqual(guessed, str(actual_xml.resolve()))

    def test_in_place_run_tree_keeps_existing_paths(self) -> None:
        repo_root = Path(self.temporary.name) / "repo"
        recorded_root = Path("build/runs/fixture")
        run_root = repo_root / recorded_root
        artifact = run_root / "fixture_test/results/results.xml"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("<testsuites/>\n", encoding="utf-8")

        resolved = collect_results._artifact_path(
            repo_root,
            run_root,
            str(recorded_root / "fixture_test/results/results.xml"),
            recorded_root,
        )

        self.assertEqual(resolved, artifact)


if __name__ == "__main__":
    unittest.main()
