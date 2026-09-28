# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Tests for `--waive`: re-grading a finished run against a coverage policy.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import dataclasses
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_coverage_closure as closure  # noqa: E402
from runlib.cli import (  # noqa: E402
    _flag_was_set,
    _waive_recorded_run,
    cmd_waive,
    parse_args,
    validate_mode_options,
    validate_waive_options,
)
from runlib.models import ConfigError, Dut  # noqa: E402

DUT = closure.DUT
TOOL = closure.TOOL
SIMULATORS = {TOOL: {"supports_cov": closure.SUPPORTED_METRICS}}
COVERAGE_FILES = {
    name: rel for name, rel in closure.GRADED_FILES.items() if name != "cov_report.log"
}
RUN_FILES = {**closure.GRADED_FILES, "result.json": Path("run/result.json")}
REGRESSION_REL = closure.REGRESSION_REL
NATIVE_REL = Path("dut/cov/config/verilator/verilator_native.cfg")
WAIVE_CAPTURE_EN_FALL = """
[[holes]]
id = "toggle-capture_en-fall"
title = "capture_en never falls"
category = "tied_off"
disposition = "waive"
status = "accepted"
confidence = "high"
rationale = "capture_en is tied low in this configuration."
owner = "fixture-dv"
reviewer = "fixture-dv"
[[holes.native]]
tool = "verilator"
metric_family = "toggle"
native_locator = "*|o=scan_ctrl_i.capture_en:1->0|*"
"""
# The open review hole becomes an accepted waiver.
ACCEPT_RUN_TEST_IDLE = (
    ('category = "missing_stimulus"', 'category = "out_of_scope"'),
    ('disposition = "cover"', 'disposition = "waive"'),
    ('status = "open"', 'status = "accepted"'),
    ('confidence = "medium"', 'confidence = "high"'),
)
NO_MATCH = (
    'native_locator = "*|o=scan_ctrl_i.capture_en:0->1|*"',
    'native_locator = "*|o=scan_ctrl_i.no_such_signal:0->1|*"',
)


def make_flow(root: Path) -> Dut:
    return dataclasses.replace(
        closure.make_flow(root), raw={"coverage": {TOOL: closure.tool_coverage_cfg()}}
    )


def stage_finished_run(root: Path, run_rel: str = "run") -> Path:
    """Stage a finished, coverage-graded run (report FAIL on thresholds) recorded at `root/run`,
    moved to `root/run_rel` when that differs, as a run tree relocated after the fact."""
    run_dir = closure.finish_run(root, "run")
    if run_rel == "run":
        return run_dir
    target = root / run_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(run_dir), str(target))
    return target


def graded_key_sets(root: Path) -> dict[str, set[str]]:
    """The top-level keys of every graded coverage file under `root`."""
    return {name: set(read_json(root / rel)) for name, rel in COVERAGE_FILES.items()}


def make_policy_failure(root: Path, run_dir: Path) -> None:
    """Turn the staged run into one whose grade failed on the policy (ERROR / config_error)."""
    for name in ("summary.json", "coverage-details.json", "policy-application.json"):
        (run_dir / "cov" / "report" / name).unlink()
    closure.write_manifest(run_dir, root)
    result = read_json(run_dir / "result.json")
    record = cov_report_record(result)
    record.update(
        {
            "status": "ERROR",
            "return_code": 2,
            "reason": "policy: hole `toggle-capture_en-rise` matched 0 observation(s), expected 1",
            "failure_buckets": [
                {
                    "kind": "config_error",
                    "signature": "policy: hole `toggle-capture_en-rise` matched 0 observation(s)",
                    "count": 1,
                    "examples": [record["log"]],
                }
            ],
        }
    )
    for key in ("coverage_summary", "coverage_details", "coverage_policy_application"):
        record["artifacts"].pop(key)
    result.update({"status": "ERROR", "exit_code": 2})
    write_json_file(run_dir / "result.json", result)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def edit_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def strip_native_files(policy_text: str) -> str:
    """The policy text without its `[[native_files]]` table."""
    start = policy_text.index("[[native_files]]")
    end = policy_text.index("[[holes]]", start)
    return policy_text[:start] + policy_text[end:]


def cov_report_record(result: dict) -> dict:
    return next(stage for stage in result["stages"] if stage["name"] == "cov_report")


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def waive_argv(run_dir: Path, *extra: str, policy: Path | None = None) -> list[str]:
    argv = ["--dut", DUT, "--run-dir", str(run_dir), "--ui", "plain", *extra, "--waive"]
    if policy is not None:
        argv.append(str(policy))
    return argv


def run_waive(
    root: Path, run_dir: Path, *extra: str, policy: Path | None = None
) -> tuple[int, str, str]:
    """Drive `cmd_waive` with the fixture flow standing in for DUT resolution."""
    args = parse_args(waive_argv(run_dir, *extra, policy=policy))
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch("runlib.cli.resolve_dut", return_value=make_flow(root)),
        mock.patch("runlib.cli.validate_flow"),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        rc = cmd_waive(root, SIMULATORS, {}, {}, args)
    return rc, out.getvalue(), err.getvalue()


class WaiveOptions(unittest.TestCase):
    def test_bare_waive_selects_the_configured_policy(self):
        args = parse_args(["--dut", DUT, "--run-dir", "run", "--waive"])
        self.assertEqual(args.waive, "")
        self.assertTrue(_flag_was_set(args, "waive"))
        validate_waive_options(args)

    def test_waive_takes_a_policy_file(self):
        args = parse_args(["--dut", DUT, "--run-dir", "run", "--waive", "w.toml"])
        self.assertEqual(args.waive, "w.toml")

    def test_waive_requires_run_dir(self):
        with self.assertRaisesRegex(ConfigError, "--run-dir"):
            validate_waive_options(parse_args(["--dut", DUT, "--waive"]))

    def test_run_options_are_rejected(self):
        for extra in (
            ["--items", "x"],
            ["--stage", "sim"],
            ["--tag", "smoke"],
            ["--build-only"],
            ["--run-only"],
            ["--dry-run"],
            ["--cov"],
            ["--regress"],
            ["--seed", "3"],
            ["--target", "default"],
            ["--waves"],
            ["--define", "X=1"],
        ):
            with self.subTest(flag=extra[0]):
                args = parse_args(["--dut", DUT, "--run-dir", "run", *extra, "--waive"])
                with self.assertRaisesRegex(ConfigError, f"{extra[0]} cannot be combined"):
                    validate_waive_options(args)

    def test_companions_are_accepted(self):
        args = parse_args(
            [
                "--dut",
                DUT,
                "--run-dir",
                "run",
                "--tool",
                TOOL,
                "--framework",
                "cocotb",
                "--fail-under",
                "50",
                "--verbose",
                "--quiet",
                "--waive",
            ]
        )
        validate_waive_options(args)

    def test_waive_is_simulation_only(self):
        args = parse_args(["--dut", DUT, "--mode", "formal", "--run-dir", "run", "--waive"])
        with self.assertRaisesRegex(ConfigError, "--waive is simulation-only"):
            validate_mode_options(args)


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def assert_exit_2_without_writes(self, run_dir: Path, **kwargs) -> str:
        before = tree_bytes(self.root)
        rc, out, err = run_waive(self.root, run_dir, **kwargs)
        self.assertEqual(rc, 2, err)
        self.assertTrue(err.startswith("ERROR: "), err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")
        self.assertEqual(tree_bytes(self.root), before)
        return err

    def assert_artifacts_exist(self, artifacts: dict, where: str) -> None:
        for key, value in artifacts.items():
            if value is None:
                continue
            with self.subTest(file=where, artifact=key):
                self.assertTrue((self.root / value).exists(), f"{where} {key}={value!r}")

    def write_waive_file(self, run_dir: Path, name: str = "waivers.toml") -> Path:
        """A policy beside the DUT's that waives every uncovered toggle point."""
        configured = self.root / closure.POLICY_REL
        text = configured.read_text(encoding="utf-8")
        for old, new in ACCEPT_RUN_TEST_IDLE:
            assert old in text, old
            text = text.replace(old, new)
        policy = configured.with_name(name)
        policy.write_text(text + WAIVE_CAPTURE_EN_FALL, encoding="utf-8")
        return policy


class RecordedRun(FixtureCase):
    def test_tool_and_framework_are_recovered_from_result_json(self):
        run_dir = stage_finished_run(self.root)
        args = parse_args(waive_argv(Path("run")))
        resolved, existing, tool, framework = _waive_recorded_run(self.root, args)
        self.assertEqual(resolved, run_dir)
        self.assertEqual((tool, framework), (TOOL, "cocotb"))
        self.assertEqual(existing["flow"], DUT)

    def test_mismatches_are_rejected(self):
        run_dir = stage_finished_run(self.root)
        for argv, message in (
            (["--dut", "other", "--run-dir", str(run_dir), "--waive"], "flow is `fixture`"),
            (waive_argv(run_dir, "--tool", "vcs"), "does not match the run's tool"),
            (waive_argv(run_dir, "--framework", "uvm"), "does not match the run's framework"),
        ):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(ConfigError, message):
                    _waive_recorded_run(self.root, parse_args(argv))

    def test_missing_result_json_exits_2(self):
        run_dir = self.root / "empty"
        run_dir.mkdir()
        err = self.assert_exit_2_without_writes(run_dir)
        self.assertIn("result.json", err)


class WaiveRegrade(FixtureCase):
    def test_recorded_policy_reproduces_every_file(self):
        run_dir = stage_finished_run(self.root)
        before = tree_bytes(self.root)
        rc, out, err = run_waive(self.root, run_dir)
        self.assertEqual((rc, err), (1, ""))
        self.assertIn("coverage=FAIL status=FAIL", out)
        self.assertEqual(tree_bytes(self.root), before)

    def test_waiver_flips_the_threshold_verdict(self):
        run_dir = stage_finished_run(self.root)
        old_result = read_json(run_dir / "result.json")
        old_record = cov_report_record(old_result)
        old_keys = graded_key_sets(self.root)
        old_log = (run_dir / "stages" / "cov_report" / "logs" / "cov_report.log").read_bytes()
        rc, out, err = run_waive(
            self.root, run_dir, "--fail-under", "50", policy=self.write_waive_file(run_dir)
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("coverage=PASS status=PASS", out)
        summary = read_json(run_dir / "cov" / "report" / "summary.json")
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["threshold"], 50.0)
        self.assertTrue(all(outcome["met"] for outcome in summary["policy_thresholds"]))
        self.assertEqual(summary["holes_summary"]["accepted"], 3)
        result = read_json(run_dir / "result.json")
        record = cov_report_record(result)
        self.assertEqual(
            (record["status"], record["return_code"], record["reason"], record["failure_buckets"]),
            ("PASS", 0, "process completed successfully", []),
        )
        self.assertEqual(set(record), set(old_record))
        self.assertEqual((result["status"], result["exit_code"]), ("PASS", 0))
        self.assertTrue(result["coverage"]["threshold_met"])
        for key in ("generated_at", "run_dir", "tool_version", "tool_versions", "overrides"):
            with self.subTest(key=key):
                self.assertEqual(result[key], old_result[key])
        for old_stage, new_stage in zip(old_result["stages"], result["stages"], strict=True):
            if old_stage["name"] != "cov_report":
                self.assertEqual(new_stage, old_stage)
        for key in ("name", "item", "duration_sec", "started_at", "ended_at", "log", "metadata"):
            self.assertEqual(record[key], old_record[key])
        regression = read_json(run_dir / REGRESSION_REL)
        self.assertEqual((regression["status"], regression["exit_code"]), ("PASS", 0))
        self.assertNotIn("coverage", regression)
        self.assertTrue(regression["artifacts"]["coverage_summary"])
        self.assertEqual(graded_key_sets(self.root), old_keys)
        self.assertEqual(
            (run_dir / "stages" / "cov_report" / "logs" / "cov_report.log").read_bytes(), old_log
        )

    def test_threshold_defaults_to_the_recorded_value(self):
        run_dir = stage_finished_run(self.root)
        rc, out, err = run_waive(self.root, run_dir, policy=self.write_waive_file(run_dir))
        self.assertEqual(rc, 1, err)
        self.assertIn("coverage=FAIL", out)
        summary = read_json(run_dir / "cov" / "report" / "summary.json")
        self.assertEqual(summary["threshold"], 60.0)
        self.assertFalse(summary["compatibility_threshold_met"])
        self.assertTrue(all(outcome["met"] for outcome in summary["policy_thresholds"]))
        record = cov_report_record(read_json(run_dir / "result.json"))
        self.assertEqual(record["failure_buckets"][0]["kind"], "coverage_threshold")
        self.assertEqual(record["failure_buckets"][0]["examples"], [record["log"]])

    def test_relocated_tree_grades_and_keeps_the_recorded_run_dir(self):
        run_dir = stage_finished_run(self.root, "elsewhere/run")
        rc, _out, err = run_waive(self.root, run_dir)
        self.assertEqual((rc, err), (1, ""))
        result = read_json(run_dir / "result.json")
        self.assertEqual(result["run_dir"], "run")
        record = cov_report_record(result)
        graded = {
            k: v
            for k, v in record["artifacts"].items()
            if k.startswith("coverage_") and k != "coverage_inputs" and k != "coverage_manifest"
        }
        self.assertEqual(graded["coverage_report"], "elsewhere/run/cov/report")
        self.assert_artifacts_exist(graded, "cov_report record")
        summary = read_json(run_dir / "cov" / "report" / "summary.json")
        manifest = read_json(run_dir / "cov" / "coverage.json")
        self.assertEqual(manifest["artifacts"]["merged"], "elsewhere/run/cov/merged.dat")
        self.assert_artifacts_exist(summary["artifacts"], "summary.json")
        self.assert_artifacts_exist(manifest["artifacts"], "coverage.json")
        coverage = result["coverage"]
        self.assert_artifacts_exist(
            {key: coverage[key] for key in ("merged", "manifest", "report", "summary")},
            "result.json coverage",
        )

    def test_host_values_are_carried_with_an_empty_path(self):
        run_dir = stage_finished_run(self.root)
        old_result = read_json(run_dir / "result.json")
        with mock.patch.dict(os.environ, {"PATH": ""}):
            rc, _out, err = run_waive(
                self.root, run_dir, "--fail-under", "50", policy=self.write_waive_file(run_dir)
            )
        self.assertEqual(rc, 0, err)
        summary = read_json(run_dir / "cov" / "report" / "summary.json")
        manifest = read_json(run_dir / "cov" / "coverage.json")
        result = read_json(run_dir / "result.json")
        self.assertEqual(summary["tool_versions"], {TOOL: closure.TOOL_VERSION})
        self.assertEqual(summary["supported_metrics"], closure.SUPPORTED_METRICS)
        self.assertEqual(manifest["tool_version"], closure.TOOL_VERSION)
        self.assertEqual(manifest["generated_at"], "2026-09-01T08:00:00+00:00")
        self.assertEqual(result["tool_version"], old_result["tool_version"])

    def test_second_run_is_idempotent(self):
        run_dir = stage_finished_run(self.root)
        policy = self.write_waive_file(run_dir)
        self.assertEqual(run_waive(self.root, run_dir, "--fail-under", "50", policy=policy)[0], 0)
        after_first = tree_bytes(self.root)
        self.assertEqual(run_waive(self.root, run_dir, "--fail-under", "50", policy=policy)[0], 0)
        self.assertEqual(tree_bytes(self.root), after_first)

    def test_exit_2_paths_leave_the_run_untouched(self):
        cases = {
            "policy selector matches nothing": lambda run_dir: edit_text(
                self.root / closure.POLICY_REL, *NO_MATCH
            ),
            "merged database deleted": lambda run_dir: (run_dir / "cov" / "merged.dat").unlink(),
            "manifest dut edited": lambda run_dir: edit_text(
                run_dir / "cov" / "coverage.json", '"dut": "fixture"', '"dut": "other"'
            ),
            "raw details deleted": lambda run_dir: (
                run_dir / "cov" / "report" / "coverage-details.raw.json"
            ).unlink(),
            "report directory deleted": lambda run_dir: shutil.rmtree(run_dir / "cov" / "report"),
            "cov_report record deleted": lambda run_dir: self._drop_record(run_dir),
            "record bucket is tool_error": lambda run_dir: edit_text(
                run_dir / "result.json", '"kind": "coverage_threshold"', '"kind": "tool_error"'
            ),
            "configured policy missing": lambda run_dir: (self.root / closure.POLICY_REL).unlink(),
            "native policy file edited": lambda run_dir: (self.root / NATIVE_REL).write_text(
                "changed\n", encoding="utf-8"
            ),
            "manifest policy block missing": lambda run_dir: self._drop_manifest_policy(run_dir),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                root_backup = self.root
                self.root = Path(tempfile.mkdtemp()).resolve()
                try:
                    run_dir = stage_finished_run(self.root)
                    mutate(run_dir)
                    self.assert_exit_2_without_writes(run_dir)
                finally:
                    shutil.rmtree(self.root, ignore_errors=True)
                    self.root = root_backup

    def _drop_manifest_policy(self, run_dir: Path) -> None:
        manifest = read_json(run_dir / "cov" / "coverage.json")
        del manifest["policy"]
        write_json_file(run_dir / "cov" / "coverage.json", manifest)

    def _drop_record(self, run_dir: Path) -> None:
        result = read_json(run_dir / "result.json")
        result["stages"] = [s for s in result["stages"] if s["name"] != "cov_report"]
        write_json_file(run_dir / "result.json", result)

    def test_policy_file_for_another_dut_exits_2(self):
        run_dir = stage_finished_run(self.root)
        policy = self.root / "other.toml"
        policy.write_text(
            (self.root / closure.POLICY_REL)
            .read_text(encoding="utf-8")
            .replace('dut = "fixture"', 'dut = "other"'),
            encoding="utf-8",
        )
        err = self.assert_exit_2_without_writes(run_dir, policy=policy)
        self.assertIn("does not match", err)

    def test_policy_file_without_the_recorded_native_files_exits_2(self):
        run_dir = stage_finished_run(self.root)
        configured = self.root / closure.POLICY_REL
        policy = configured.with_name("no-native.toml")
        policy.write_text(
            strip_native_files(configured.read_text(encoding="utf-8")), encoding="utf-8"
        )
        err = self.assert_exit_2_without_writes(run_dir, policy=policy)
        self.assertIn("native policy files differ", err)
        self.assertIn("--stage cov_report", err)

    def test_missing_policy_file_exits_2(self):
        run_dir = stage_finished_run(self.root)
        err = self.assert_exit_2_without_writes(run_dir, policy=self.root / "nope.toml")
        self.assertIn("does not exist", err)

    def test_unexpected_errors_exit_2_with_a_traceback(self):
        run_dir = stage_finished_run(self.root)
        before = tree_bytes(self.root)
        err = io.StringIO()
        with (
            mock.patch("runlib.cli.resolve_dut", return_value=make_flow(self.root)),
            mock.patch("runlib.cli.validate_flow"),
            mock.patch("runlib.cli.waive_run", side_effect=RuntimeError("boom")),
            redirect_stderr(err),
        ):
            rc = cmd_waive(self.root, SIMULATORS, {}, {}, parse_args(waive_argv(run_dir)))
        self.assertEqual(rc, 2)
        self.assertIn("Traceback", err.getvalue())
        self.assertIn("boom", err.getvalue())
        self.assertEqual(tree_bytes(self.root), before)


class PolicyFailureRepair(FixtureCase):
    def test_repair_creates_the_summary_and_grades_the_record(self):
        run_dir = stage_finished_run(self.root)
        graded_record = cov_report_record(read_json(run_dir / "result.json"))
        graded_keys = graded_key_sets(self.root)
        make_policy_failure(self.root, run_dir)
        self.assertFalse((run_dir / "cov" / "report" / "summary.json").exists())
        rc, out, err = run_waive(self.root, run_dir)
        self.assertEqual((rc, err), (1, ""))
        self.assertIn("coverage=FAIL status=FAIL", out)
        summary = read_json(run_dir / "cov" / "report" / "summary.json")
        self.assertEqual(summary["threshold"], 60.0)
        result = read_json(run_dir / "result.json")
        record = cov_report_record(result)
        self.assertEqual(set(record), set(graded_record))
        self.assertEqual(set(record["artifacts"]), set(graded_record["artifacts"]))
        self.assertEqual(
            (record["status"], record["return_code"], record["failure_buckets"][0]["kind"]),
            ("FAIL", 1, "coverage_threshold"),
        )
        self.assertEqual((result["status"], result["exit_code"]), ("FAIL", 1))
        self.assertEqual(graded_key_sets(self.root), graded_keys)
        regression = read_json(run_dir / REGRESSION_REL)
        self.assertEqual((regression["status"], regression["exit_code"]), ("FAIL", 1))

    def test_repair_with_the_failing_policy_stays_exit_2(self):
        run_dir = stage_finished_run(self.root)
        make_policy_failure(self.root, run_dir)
        edit_text(self.root / closure.POLICY_REL, *NO_MATCH)
        err = self.assert_exit_2_without_writes(run_dir)
        self.assertIn("expected 1", err)


if __name__ == "__main__":
    unittest.main()
