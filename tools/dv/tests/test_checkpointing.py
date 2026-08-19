# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Integration coverage for durable DV runner checkpoints."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
DV_TOOLS = REPO_ROOT / "tools" / "dv"
sys.path.insert(0, str(DV_TOOLS))

from dashboard import collect_results  # noqa: E402
from runlib import cli  # noqa: E402
from runlib import stages as stage_lib  # noqa: E402
from runlib.compat import UTC  # noqa: E402
from runlib.models import Flow, StageResult, TestCatalog, TestEntry  # noqa: E402


def fixture_flow() -> Flow:
    return Flow(
        name="checkpoint_fixture",
        kind="dv",
        description="checkpoint integration fixture",
        framework="cocotb",
        visibility="public",
        runnability="open",
        license="none",
        root=".",
        default_tool="fixture",
        tools=["fixture"],
        path=REPO_ROOT / "checkpoint_fixture.toml",
        raw={
            "native": {"stages": {"sim": {"kind": "fixture"}}},
            "scheduler": {"default_executor": "local", "allowed": ["local"]},
        },
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


def fixture_catalog(leaf_count: int) -> TestCatalog:
    tests = {
        f"leaf_{index}": TestEntry(
            name=f"leaf_{index}",
            module=f"fixture.leaf_{index}",
        )
        for index in range(leaf_count)
    }
    return TestCatalog(
        path=REPO_ROOT / "checkpoint_fixture_testlist.toml",
        tests=tests,
        groups={"all": list(tests)},
    )


def fixture_result(
    stage_name: str,
    item: str,
    started_at: str,
    duration_sec: float,
) -> StageResult:
    return StageResult(
        stage=stage_name,
        item=item,
        status="PASS",
        return_code=0,
        duration_sec=duration_sec,
        started_at=started_at,
        ended_at=datetime.now(UTC).isoformat(),
        reason="fixture leaf passed",
        target="default",
    )


def run_fixture(args: argparse.Namespace) -> int:
    flow = fixture_flow()
    catalog = fixture_catalog(args.leaf_count)
    sim_cfg = {
        "defaults": {"target": "default", "seed": 1},
        "targets": {"default": {"build_dir": "build/checkpoint-fixture"}},
    }
    runner_args = cli.parse_args([
        "--dut",
        flow.name,
        "--items",
        "all",
        "--tool",
        "fixture",
        "--regress",
        "--reseed",
        "1",
        "--sim-jobs",
        str(args.sim_jobs),
        "--run-dir",
        str(args.run_dir),
        "--quiet",
        "--ui",
        "plain",
    ])

    release_file = Path(args.release_file) if args.release_file else None
    active_file = Path(args.active_file) if args.active_file else None

    def fake_run_stage(*stage_args: object, **_stage_kwargs: object) -> StageResult:
        stage_name = str(stage_args[4])
        item = str(stage_args[5])
        cancellation_event = stage_args[6]._cancellation_event
        started = datetime.now(UTC).isoformat()
        if active_file is not None:
            active_file.parent.mkdir(parents=True, exist_ok=True)
            with active_file.open("a", encoding="utf-8") as stream:
                stream.write(f"{item}\n")
                stream.flush()
        if release_file is not None:
            deadline = time.monotonic() + 10
            while not release_file.exists():
                if cancellation_event.is_set():
                    raise RuntimeError("fixture stage cancelled")
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"fixture release file was not created: {release_file}")
                time.sleep(0.01)
        item_index = int(item.removeprefix("leaf_"))
        delay = args.fast_delay if item_index < args.fast_leaves else args.delay
        if args.child_sleep:
            run_dir = Path(stage_args[8])
            item_dir = run_dir / "fixture-children" / item
            pid_file = item_dir / "pid"
            rc = stage_lib.run_subprocess(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os, pathlib, sys, time; "
                        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
                        "time.sleep(float(sys.argv[2]))"
                    ),
                    str(pid_file),
                    str(args.child_sleep),
                ],
                REPO_ROOT,
                item_dir / "stage.log",
                False,
                item_dir / "stage.sh",
                item_dir / "env.txt",
                True,
            )
            if rc:
                raise RuntimeError(f"fixture child exited {rc}")
            return fixture_result(stage_name, item, started, args.child_sleep)
        if cancellation_event.wait(delay):
            raise RuntimeError("fixture stage cancelled")
        return fixture_result(stage_name, item, started, delay)

    simulators = {"fixture": {"binary": "true"}}
    with (
        mock.patch.object(cli, "load_sim_cfg", return_value=sim_cfg),
        mock.patch.object(cli, "merge_simulator_defaults", side_effect=lambda cfg, *_args: cfg),
        mock.patch.object(cli, "load_test_catalog", return_value=catalog),
        mock.patch.object(cli, "run_stage", side_effect=fake_run_stage),
        mock.patch.object(cli, "tool_versions", return_value={"python": sys.version.split()[0]}),
        mock.patch.object(
            cli,
            "git_info",
            return_value={"commit": "fixture", "branch": "fixture", "dirty": "false"},
        ),
    ):
        return cli.run_flow(
            root=REPO_ROOT,
            flow=flow,
            simulators=simulators,
            policies={},
            args=runner_args,
        )


class CheckpointIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        scratch = os.environ.get("TMPDIR")
        scratch_dir = scratch if scratch and Path(scratch).is_dir() else None
        self.temporary = tempfile.TemporaryDirectory(
            prefix="ocah-checkpoint-",
            dir=scratch_dir,
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.processes: list[subprocess.Popen[str]] = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def spawn_fixture(
        self,
        *,
        leaf_count: int = 3,
        sim_jobs: int = 2,
        delay: float = 0.05,
        fast_leaves: int = 0,
        fast_delay: float = 0.02,
        release_file: Path | None = None,
        active_file: Path | None = None,
        child_sleep: float = 0,
    ) -> tuple[subprocess.Popen[str], Path]:
        run_dir = self.root / f"run-{len(self.processes)}"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--fixture",
            "--run-dir",
            str(run_dir),
            "--leaf-count",
            str(leaf_count),
            "--sim-jobs",
            str(sim_jobs),
            "--delay",
            str(delay),
            "--fast-leaves",
            str(fast_leaves),
            "--fast-delay",
            str(fast_delay),
            "--child-sleep",
            str(child_sleep),
        ]
        if release_file is not None:
            command.extend(["--release-file", str(release_file)])
        if active_file is not None:
            command.extend(["--active-file", str(active_file)])
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.processes.append(process)
        return process, run_dir

    def wait_for_result(
        self,
        process: subprocess.Popen[str],
        run_dir: Path,
        predicate,
        *,
        timeout: float = 8,
    ) -> dict[str, object]:
        path = run_dir / "result.json"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    self.fail(f"checkpoint was not atomic: {path}: {exc}")
                if predicate(payload):
                    return payload
            if process.poll() is not None:
                output = process.communicate()[0]
                self.fail(
                    f"fixture exited before expected checkpoint: rc={process.returncode}\n{output}"
                )
            time.sleep(0.01)
        self.fail(f"timed out waiting for checkpoint predicate: {path}")

    def finish(
        self,
        process: subprocess.Popen[str],
        *,
        timeout: float = 10,
    ) -> tuple[int, str]:
        try:
            output = process.communicate(timeout=timeout)[0]
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate()[0]
            self.fail(f"fixture did not exit within {timeout}s\n{output}")
        return int(process.returncode), output

    def assert_leaf_partition(self, progress: dict[str, object]) -> None:
        expected = {entry["id"] for entry in progress["expected"]}
        completed = {entry["id"] for entry in progress["completed"]}
        missing = {entry["id"] for entry in progress["missing"]}
        interrupted = {entry["id"] for entry in progress["interrupted"]}
        active = {entry["id"] for entry in progress["active"]}
        self.assertFalse(
            active,
            f"final interruption checkpoint retained active leaves: {sorted(active)}",
        )
        self.assertEqual(
            expected,
            completed | missing | interrupted,
            (
                "leaf partition mismatch: "
                f"expected={sorted(expected)} completed={sorted(completed)} "
                f"missing={sorted(missing)} interrupted={sorted(interrupted)}"
            ),
        )
        self.assertFalse(completed & missing)
        self.assertFalse(completed & interrupted)
        self.assertFalse(missing & interrupted)
        self.assertEqual(progress["expected_count"], len(expected))
        self.assertEqual(progress["completed_count"], len(completed))
        self.assertEqual(progress["missing_count"], len(missing))
        self.assertEqual(progress["interrupted_count"], len(interrupted))

    def test_initial_checkpoint_is_replaced_by_final_result(self) -> None:
        release_file = self.root / "release"
        process, run_dir = self.spawn_fixture(release_file=release_file)

        initial = self.wait_for_result(
            process,
            run_dir,
            lambda payload: payload.get("status") == "UNKNOWN",
        )
        progress = initial["progress"]
        self.assertEqual(progress["state"], "running")
        self.assertEqual(progress["expected_count"], 3)
        self.assertEqual(progress["completed_count"], 0)
        self.assertEqual(progress["missing_count"], 3)
        release_file.touch()

        return_code, output = self.finish(process)
        self.assertEqual(return_code, 0, f"fixture failed unexpectedly\n{output}")
        final = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(final["schema_version"], 1)
        self.assertEqual(final["status"], "PASS")
        self.assertNotIn("progress", final)
        self.assertNotIn("interruption", final)
        regression = json.loads(
            (run_dir / "stages" / "regress" / "regression.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(regression["status"], "PASS")
        self.assertEqual(len(regression["jobs"]), 3)

    def test_checkpoint_refreshes_are_always_valid_json(self) -> None:
        process, run_dir = self.spawn_fixture(
            leaf_count=16,
            sim_jobs=4,
            delay=0.03,
        )
        path = run_dir / "result.json"
        statuses: set[str] = set()
        sequences: set[int] = set()
        while process.poll() is None:
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    self.fail(f"observed a partially written checkpoint: {exc}")
                statuses.add(str(payload["status"]))
                if "progress" in payload:
                    sequences.add(int(payload["progress"]["sequence"]))
            time.sleep(0.002)
        return_code, output = self.finish(process)
        self.assertEqual(return_code, 0, f"fixture failed unexpectedly\n{output}")
        self.assertIn("UNKNOWN", statuses)
        self.assertGreater(
            len(sequences),
            1,
            f"expected multiple checkpoint refreshes, observed sequences={sorted(sequences)}",
        )
        final = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(final["status"], "PASS")

    def test_coverage_replay_cannot_promote_interrupted_checkpoint(self) -> None:
        existing = {
            "status": "ERROR",
            "exit_code": 2,
            "progress": {"state": "interrupted"},
            "interruption": {"signal": "SIGTERM"},
            "stages": [{"name": "sim", "status": "PASS"}],
        }
        replay = {
            "status": "PASS",
            "generated_at": "fixture",
            "coverage": {"status": "PASS"},
            "stages": [{"name": "cov_report", "status": "PASS"}],
        }

        merged = cli._merge_coverage_replay_result(existing, replay)

        self.assertEqual(
            merged["status"],
            "ERROR",
            f"coverage replay promoted interrupted checkpoint: {merged}",
        )
        self.assertEqual(merged["exit_code"], 2)
        self.assertEqual(merged["progress"]["state"], "interrupted")
        self.assertEqual(merged["interruption"]["signal"], "SIGTERM")

    def test_sigint_cancellation_preserves_completed_and_unfinished_leaves(self) -> None:
        process, run_dir = self.spawn_fixture(
            leaf_count=3,
            sim_jobs=2,
            delay=1.0,
            fast_leaves=1,
            fast_delay=0.05,
        )
        self.wait_for_result(
            process,
            run_dir,
            lambda payload: payload.get("progress", {}).get("completed_count") == 1,
        )
        os.kill(process.pid, signal.SIGINT)

        return_code, output = self.finish(process)
        self.assertEqual(return_code, 128 + signal.SIGINT, output)
        interrupted = json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(interrupted["status"], "ERROR")
        self.assertEqual(interrupted["interruption"]["signal"], "SIGINT")
        self.assertEqual(interrupted["progress"]["state"], "interrupted")
        self.assertEqual(interrupted["progress"]["completed_count"], 1)
        self.assert_leaf_partition(interrupted["progress"])

    def test_sigterm_timeout_preserves_and_publishes_leaf_partition(self) -> None:
        active_file = self.root / "active"
        process, run_dir = self.spawn_fixture(
            leaf_count=3,
            sim_jobs=2,
            child_sleep=30,
            active_file=active_file,
        )
        deadline = time.monotonic() + 8
        pid_files = [
            run_dir / "fixture-children" / f"leaf_{index}" / "pid"
            for index in range(2)
        ]
        while time.monotonic() < deadline:
            if active_file.is_file() and all(path.is_file() for path in pid_files):
                active = active_file.read_text(encoding="utf-8").splitlines()
                if len(active) >= 2:
                    break
            if process.poll() is not None:
                output = process.communicate()[0]
                self.fail(f"fixture exited before timeout signal\n{output}")
            time.sleep(0.01)
        else:
            self.fail("two fixture child processes did not start before timeout signal")
        child_pids = [int(path.read_text(encoding="utf-8")) for path in pid_files]
        interrupted_at = time.monotonic()
        os.kill(process.pid, signal.SIGTERM)

        return_code, output = self.finish(process, timeout=5)
        self.assertLess(
            time.monotonic() - interrupted_at,
            3,
            f"runner did not stop active leaves promptly\n{output}",
        )
        self.assertEqual(return_code, 128 + signal.SIGTERM, output)
        for pid in child_pids:
            with self.assertRaises(
                ProcessLookupError,
                msg=f"fixture child process survived runner cancellation: pid={pid}",
            ):
                os.kill(pid, 0)
        interrupted = json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(interrupted["status"], "ERROR")
        self.assertEqual(interrupted["interruption"]["signal"], "SIGTERM")
        self.assertEqual(interrupted["progress"]["completed_count"], 0)
        self.assertEqual(interrupted["progress"]["interrupted_count"], 2)
        self.assertEqual(interrupted["progress"]["missing_count"], 1)
        self.assert_leaf_partition(interrupted["progress"])

        with mock.patch.object(
            collect_results,
            "load_test_catalog",
            return_value=fixture_catalog(3),
        ):
            normalized = collect_results.collect_flow_result(
                REPO_ROOT,
                fixture_flow(),
                run_dir,
            )
        self.assertEqual(normalized["status"], "FAIL")
        self.assertEqual(normalized["source"]["collector"], "run_dv-result")
        self.assertEqual(normalized["source"]["native_status"], "ERROR")
        self.assertEqual(
            normalized["run_metadata"]["progress"],
            interrupted["progress"],
        )
        self.assertEqual(
            normalized["run_metadata"]["interruption"]["signal"],
            "SIGTERM",
        )


def fixture_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--leaf-count", type=int, default=3)
    parser.add_argument("--sim-jobs", type=int, default=2)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--fast-leaves", type=int, default=0)
    parser.add_argument("--fast-delay", type=float, default=0.02)
    parser.add_argument("--child-sleep", type=float, default=0)
    parser.add_argument("--release-file")
    parser.add_argument("--active-file")
    return parser


if __name__ == "__main__":
    if "--fixture" in sys.argv:
        raise SystemExit(run_fixture(fixture_parser().parse_args()))
    unittest.main()
