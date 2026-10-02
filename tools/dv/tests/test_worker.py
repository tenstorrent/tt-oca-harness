# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the leaf manifest, the worker entry point, and the read-only worker branch of
``run_dv.py``.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import worker  # noqa: E402
from runlib.cli import parse_args  # noqa: E402
from runlib.config import load_test_catalog  # noqa: E402
from runlib.duts import resolve_dut  # noqa: E402
from runlib.executors.base import LeafTask, ResourceRequest, task_identifier  # noqa: E402
from runlib.executors.manifest import (  # noqa: E402
    DIGEST_KEY,
    ManifestError,
    attempt_args,
    completion_path,
    execute_attempt,
    graded_path,
    load_manifest,
    manifest_digest,
    manifest_path,
    manifest_payload,
    task_from_manifest,
    write_manifest,
)
from runlib.models import StageResult  # noqa: E402
from runlib.results import exit_code_for_status, write_result  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_DV = REPO_ROOT / "tools" / "dv" / "run_dv.py"
DUT = "dtp"


def stage_result(task: LeafTask, status: str = "PASS") -> StageResult:
    return StageResult(
        stage=task.stage,
        item=task.item,
        status=status,
        return_code=0 if status == "PASS" else 1,
        duration_sec=1.0,
        started_at="2026-09-20T00:00:00+00:00",
        ended_at="2026-09-20T00:00:01+00:00",
        log=str(task.leaf_dir / "logs" / f"{task.item}.log"),
        metadata={"seed": task.seed, "attempt": task.attempt},
        target=task.target,
    )


class ManifestCase(unittest.TestCase):
    """A run directory inside the checkout, so leaf paths are repo-relative as in a real run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.flow = resolve_dut(REPO_ROOT, DUT)
        cls.catalog = load_test_catalog(cls.flow, REPO_ROOT)
        cls.item = next(iter(cls.catalog.tests))

    def setUp(self) -> None:
        build = REPO_ROOT / "build"
        build.mkdir(exist_ok=True)
        self.run_dir = Path(tempfile.mkdtemp(prefix="test-worker-", dir=build)).resolve()
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)

    def task(self, attempt: int = 0, **kwargs) -> LeafTask:
        leaf_dir = self.run_dir / self.item / "seed_11" / f"attempt_{attempt}"
        return LeafTask(
            task_id=task_identifier("sim", 4, attempt, debug_only=kwargs.get("debug_only", False)),
            leaf_id=4,
            stage="sim",
            item=self.item,
            seed=11,
            attempt=attempt,
            run_dir=self.run_dir,
            leaf_dir=leaf_dir,
            target="default",
            nest=True,
            resources=ResourceRequest(queue="regress", cores=1),
            **kwargs,
        )

    def payload(self, task: LeafTask, **overrides) -> dict:
        fields = dict(
            flow=self.flow,
            root=REPO_ROOT,
            tool="verilator",
            executor="local",
            argv=["--dut", DUT, "--items", self.item, "--seed", "11"],
            ui_leaf_mode="full",
            multi_target=False,
            overlay=None,
            site=None,
            repo_commit=None,
            repo_dirty=None,
        )
        fields.update(overrides)
        return manifest_payload(task, **fields)


class ManifestTest(ManifestCase):
    def test_round_trip_and_digest(self) -> None:
        task = self.task()
        payload = self.payload(task)
        self.assertEqual(payload[DIGEST_KEY], manifest_digest(payload))
        path = write_manifest(manifest_path(self.run_dir, task.task_id), payload)
        self.assertEqual(path.name, f"{task.task_id}.json")
        loaded = load_manifest(path)
        self.assertEqual(loaded, payload)
        back = task_from_manifest(loaded)
        self.assertEqual(
            (back.task_id, back.item, back.seed, back.attempt, back.nest, back.resources),
            (task.task_id, task.item, task.seed, 0, True, task.resources),
        )
        self.assertEqual(back.leaf_dir, task.leaf_dir)
        self.assertEqual(loaded["completion"], str(completion_path(self.run_dir, task.task_id)))

    def test_edited_manifest_is_refused(self) -> None:
        task = self.task()
        path = write_manifest(manifest_path(self.run_dir, task.task_id), self.payload(task))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["seed"] = 12
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(path)
        self.assertIn(DIGEST_KEY, str(ctx.exception))

    def test_schema_and_override_guards(self) -> None:
        task = self.task()
        payload = self.payload(task)
        payload["schema_version"] = 99
        payload[DIGEST_KEY] = manifest_digest(payload)
        path = write_manifest(self.run_dir / "bad.json", payload)
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(path)
        self.assertIn("schema_version", str(ctx.exception))
        hijack = self.payload(self.task(args_overrides={"dut": "smc"}))
        path = write_manifest(self.run_dir / "hijack.json", hijack)
        with self.assertRaises(ManifestError) as ctx:
            load_manifest(path)
        self.assertIn("dut", str(ctx.exception))

    def test_attempt_args_apply_overrides_and_debug_flags(self) -> None:
        base = Namespace(waves=None, waves_on_fail="fst", wave_retention=None, quiet=False)
        debug = self.task(
            attempt=1,
            debug_only=True,
            args_overrides={"waves": "fst", "waves_on_fail": None, "wave_retention": "failed"},
            wave_failure_time={"ps": 1200},
        )
        args = attempt_args(base, debug, ui_leaf_mode="compact")
        self.assertEqual(
            (args.waves, args.waves_on_fail, args.wave_retention), ("fst", None, "failed")
        )
        self.assertTrue(args._wave_debug_rerun)
        self.assertEqual(args._wave_failure_time, {"ps": 1200})
        self.assertEqual(args._ui_leaf_mode, "compact")
        self.assertIsNone(base.waves)
        with self.assertRaises(ManifestError):
            attempt_args(base, self.task(args_overrides={"run_dir": "/elsewhere"}))

    def test_execute_attempt_writes_the_leaf_fragment(self) -> None:
        task = self.task()
        args = parse_args(["--dut", DUT, "--items", self.item])
        with mock.patch(
            "runlib.executors.manifest.run_stage", return_value=stage_result(task)
        ) as run:
            result, result_json = execute_attempt(
                flow=self.flow,
                root=REPO_ROOT,
                sim_cfg={},
                catalog=self.catalog,
                task=task,
                args=args,
                tool="verilator",
                simulators={},
                policies={},
            )
        self.assertEqual(result.status, "PASS")
        kwargs = run.call_args.kwargs
        self.assertEqual(
            (kwargs["nest"], kwargs["attempt"], kwargs["seed_override"]), (True, 0, 11)
        )
        self.assertEqual(result_json, str(task.result_json.relative_to(REPO_ROOT)))
        payload = json.loads(task.result_json.read_text(encoding="utf-8"))
        self.assertEqual((payload["status"], payload["seed"], payload["attempt"]), ("PASS", 11, 0))

    def test_dry_run_writes_no_fragment(self) -> None:
        task = self.task()
        args = parse_args(["--dut", DUT, "--items", self.item, "--dry-run"])
        with mock.patch("runlib.executors.manifest.run_stage", return_value=stage_result(task)):
            execute_attempt(
                flow=self.flow,
                root=REPO_ROOT,
                sim_cfg={},
                catalog=self.catalog,
                task=task,
                args=args,
                tool="verilator",
                simulators={},
                policies={},
            )
        self.assertFalse(task.result_json.exists())

    def leave_earlier_outputs(self, task: LeafTask) -> list[Path]:
        """What an earlier invocation into this run directory left at the attempt's paths."""
        xml = task.leaf_dir / "results" / "results.xml"
        done = completion_path(self.run_dir, task.task_id)
        for path in (xml, task.result_json, done):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        return [xml, task.result_json, done]

    def test_execute_attempt_removes_what_an_earlier_invocation_left(self) -> None:
        task = self.task()
        earlier = self.leave_earlier_outputs(task)
        args = parse_args(["--dut", DUT, "--items", self.item])
        with (
            mock.patch("runlib.executors.manifest.run_stage", side_effect=OSError("disk")),
            self.assertRaises(OSError),
        ):
            execute_attempt(
                flow=self.flow,
                root=REPO_ROOT,
                sim_cfg={},
                catalog=self.catalog,
                task=task,
                args=args,
                tool="verilator",
                simulators={},
                policies={},
            )
        self.assertEqual([path for path in earlier if path.exists()], [])

    def test_dry_run_removes_nothing(self) -> None:
        task = self.task()
        earlier = self.leave_earlier_outputs(task)
        args = parse_args(["--dut", DUT, "--items", self.item, "--dry-run"])
        with mock.patch("runlib.executors.manifest.run_stage", return_value=stage_result(task)):
            execute_attempt(
                flow=self.flow,
                root=REPO_ROOT,
                sim_cfg={},
                catalog=self.catalog,
                task=task,
                args=args,
                tool="verilator",
                simulators={},
                policies={},
            )
        self.assertEqual([path for path in earlier if not path.exists()], [])


def run_worker(path: Path) -> int:
    """The worker's exit status, with its console lines kept out of the test output."""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return worker.main([str(path)])


class WorkerMainTest(ManifestCase):
    def write(self, task: LeafTask, **overrides) -> Path:
        return write_manifest(
            manifest_path(self.run_dir, task.task_id), self.payload(task, **overrides)
        )

    def mark_graded(self, task: LeafTask) -> None:
        """The mark the coordinator leaves when it grades the attempt without this worker."""
        mark = graded_path(self.run_dir, task.task_id)
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(json.dumps({"task_id": task.task_id, "state": "LOST"}), encoding="utf-8")

    def run_worker_console(self, path: Path) -> tuple[int, str]:
        console = io.StringIO()
        with redirect_stdout(console), redirect_stderr(console):
            code = worker.main([str(path)])
        return code, console.getvalue()

    def assert_wrote_nothing(self, task: LeafTask, code: int, console: str) -> None:
        self.assertEqual(code, worker.ENVIRONMENT_ERROR_EXIT)
        self.assertFalse(task.result_json.exists())
        self.assertFalse(completion_path(self.run_dir, task.task_id).exists())
        self.assertIn("graded this attempt without its result", console)

    def test_a_graded_attempt_runs_nothing_and_leaves_the_coordinator_files(self) -> None:
        task = self.task()
        path = self.write(task)
        self.mark_graded(task)
        graded_xml = task.leaf_dir / "results" / "results.xml"
        graded_xml.parent.mkdir(parents=True)
        graded_xml.write_text("<testsuites/>\n", encoding="utf-8")
        with mock.patch("runlib.executors.manifest.run_stage") as run:
            code, console = self.run_worker_console(path)
        run.assert_not_called()
        self.assert_wrote_nothing(task, code, console)
        self.assertIn("leaving neither result.json nor the completion record", console)
        self.assertTrue(graded_xml.is_file())

    def test_a_mark_left_while_the_stage_ran_stops_both_writes(self) -> None:
        task = self.task()
        path = self.write(task)

        def stage(*_args, **_kwargs) -> StageResult:
            self.mark_graded(task)
            return stage_result(task)

        with mock.patch("runlib.executors.manifest.run_stage", side_effect=stage):
            code, console = self.run_worker_console(path)
        self.assert_wrote_nothing(task, code, console)

    def test_a_mark_left_while_the_stage_ran_stops_the_error_record(self) -> None:
        task = self.task()
        path = self.write(task)

        def stage(*_args, **_kwargs) -> StageResult:
            self.mark_graded(task)
            raise OSError("disk")

        with mock.patch("runlib.executors.manifest.run_stage", side_effect=stage):
            code, console = self.run_worker_console(path)
        self.assert_wrote_nothing(task, code, console)

    def test_a_mark_left_after_the_result_removes_it_and_stops_the_completion_record(
        self,
    ) -> None:
        task = self.task()
        path = self.write(task)
        written: list[Path] = []

        def write_then_grade(target: Path, payload: dict) -> None:
            write_result(target, payload)
            written.append(target)
            if target == task.result_json:
                self.mark_graded(task)

        with (
            mock.patch("runlib.executors.manifest.run_stage", return_value=stage_result(task)),
            mock.patch("runlib.executors.manifest.write_result", side_effect=write_then_grade),
        ):
            code, console = self.run_worker_console(path)
        self.assertEqual(written, [task.result_json])
        self.assert_wrote_nothing(task, code, console)
        self.assertIn("leaving neither result.json nor the completion record", console)

    def test_a_graded_attempt_with_an_untrusted_manifest_writes_no_result(self) -> None:
        task = self.task()
        path = self.write(task)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["item"] = "someone_else"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.mark_graded(task)
        code, console = self.run_worker_console(path)
        self.assert_wrote_nothing(task, code, console)

    def test_runs_one_attempt_and_records_completion(self) -> None:
        task = self.task()
        path = self.write(task)
        with mock.patch(
            "runlib.executors.manifest.run_stage", return_value=stage_result(task)
        ) as run:
            code = run_worker(path)
        self.assertEqual(code, 0)
        run.assert_called_once()
        called = run.call_args
        self.assertEqual(called.args[4:6], ("sim", self.item))
        self.assertEqual(called.kwargs, {"nest": True, "attempt": 0, "seed_override": 11})
        args = called.args[6]
        self.assertEqual(args.items, [self.item])
        self.assertEqual(args._cocotb_prebuilt_targets, {"default"})
        leaf = json.loads(task.result_json.read_text(encoding="utf-8"))
        self.assertEqual(leaf["status"], "PASS")
        done = json.loads(completion_path(self.run_dir, task.task_id).read_text(encoding="utf-8"))
        self.assertEqual((done["task_id"], done["status"]), (task.task_id, "PASS"))
        self.assertEqual(done["result_json"], str(task.result_json.relative_to(REPO_ROOT)))

    def test_a_build_manifest_runs_the_stage_without_an_item(self) -> None:
        task = LeafTask(
            task_id="build-hdl_compile-default",
            leaf_id=-1,
            stage="hdl_compile",
            item="",
            seed=0,
            attempt=0,
            run_dir=self.run_dir,
            leaf_dir=self.run_dir / "stages" / "regress" / "builds" / "build-hdl_compile-default",
            target="default",
            role="build",
            resources=ResourceRequest(cores=3),
        )
        path = self.write(task)
        built = StageResult(
            stage="hdl_compile",
            item=None,
            status="PASS",
            return_code=0,
            duration_sec=1.0,
            started_at="2026-09-01T00:00:00+00:00",
            ended_at="2026-09-01T00:00:01+00:00",
            metadata={"target": "default", "target_build": {"target": "default"}},
        )
        with mock.patch("runlib.executors.manifest.run_stage", return_value=built) as run:
            code = run_worker(path)
        self.assertEqual(code, 0)
        called = run.call_args
        self.assertEqual(called.args[4:6], ("hdl_compile", None))
        args = called.args[6]
        self.assertEqual(args.build_jobs, 3)
        self.assertFalse(hasattr(args, "_cocotb_prebuilt_targets"))
        fragment = json.loads(task.result_json.read_text(encoding="utf-8"))
        self.assertEqual((fragment["item"], fragment["status"]), ("", "PASS"))
        self.assertEqual(fragment["target_build"]["target"], "default")
        self.assertNotIn("target_build", fragment["metadata"])
        done = json.loads(completion_path(self.run_dir, task.task_id).read_text(encoding="utf-8"))
        self.assertEqual(done["status"], "PASS")

    def test_exit_status_follows_the_leaf_status(self) -> None:
        task = self.task()
        path = self.write(task)
        with mock.patch(
            "runlib.executors.manifest.run_stage", return_value=stage_result(task, "FAIL")
        ):
            self.assertEqual(run_worker(path), exit_code_for_status("FAIL"))

    def test_edited_manifest_leaves_an_environment_error(self) -> None:
        task = self.task()
        path = self.write(task)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["item"] = "someone_else"
        path.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch("runlib.executors.manifest.run_stage") as run:
            self.assertEqual(run_worker(path), worker.ENVIRONMENT_ERROR_EXIT)
        run.assert_not_called()
        leaf = json.loads(task.result_json.read_text(encoding="utf-8"))
        self.assertEqual(leaf["status"], "ERROR")
        self.assertTrue(leaf["reason"].startswith("environment_error:"))
        self.assertIn(DIGEST_KEY, leaf["reason"])
        self.assertEqual([b["kind"] for b in leaf["failure_buckets"]], ["environment_error"])

    def test_missing_run_tree_and_missing_manifest(self) -> None:
        task = self.task()
        payload = self.payload(task)
        payload["run_dir"] = str(self.run_dir / "elsewhere")
        payload[DIGEST_KEY] = manifest_digest(payload)
        path = write_manifest(self.run_dir / "gone.json", payload)
        self.assertEqual(run_worker(path), worker.ENVIRONMENT_ERROR_EXIT)
        self.assertEqual(run_worker(self.run_dir / "absent.json"), worker.ENVIRONMENT_ERROR_EXIT)

    def test_unknown_item_and_stage_exception(self) -> None:
        stray = self.task()
        stray = LeafTask(**{**stray.__dict__, "item": "no_such_test"})
        path = self.write(stray)
        self.assertEqual(run_worker(path), worker.ENVIRONMENT_ERROR_EXIT)
        leaf = json.loads(stray.result_json.read_text(encoding="utf-8"))
        self.assertIn("catalog", leaf["reason"])
        task = self.task(attempt=1)
        path = self.write(task)
        with mock.patch("runlib.executors.manifest.run_stage", side_effect=OSError("disk")):
            self.assertEqual(run_worker(path), worker.ENVIRONMENT_ERROR_EXIT)
        leaf = json.loads(task.result_json.read_text(encoding="utf-8"))
        self.assertEqual(leaf["status"], "ERROR")
        self.assertIn("OSError", leaf["reason"])


class BootstrapBranchTest(unittest.TestCase):
    """``run_dv.py --worker-manifest`` attaches the bridge read-only and never reaches uv."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "Bender.yml").write_text("package:\n  name: fixture\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")
        tools = self.root / "tools" / "dv"
        (tools / "runlib").mkdir(parents=True)
        shutil.copy(RUN_DV, tools / "run_dv.py")
        shutil.copy(RUN_DV.parent / "sync_python_namespace.py", tools / "sync_python_namespace.py")
        (tools / "runlib" / "__init__.py").write_text("", encoding="utf-8")
        (tools / "runlib" / "worker.py").write_text(
            "def main(argv):\n    print('STUB-WORKER', argv)\n    return 7\n", encoding="utf-8"
        )
        self.script = tools / "run_dv.py"
        empty_path = self.root / "empty-path"
        empty_path.mkdir()
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"OCAH_DV_UV_BOOTSTRAPPED", "OCAH_DV_SKIP_UV", "PYTHONPATH"}
        }
        self.env["PATH"] = str(empty_path)

    def run_dv(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *argv],
            capture_output=True,
            text=True,
            env=self.env,
            cwd=self.root,
            check=False,
        )

    def test_missing_bridge_is_an_environment_error(self) -> None:
        proc = self.run_dv("--worker-manifest", "m.json")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("namespace bridge missing", proc.stderr)
        self.assertNotIn("STUB-WORKER", proc.stdout)

    def test_worker_branch_dispatches_without_uv(self) -> None:
        (self.root / "build" / "dv" / "python").mkdir(parents=True)
        proc = self.run_dv("--worker-manifest", "m.json")
        self.assertEqual(proc.returncode, 7, proc.stderr)
        self.assertIn("STUB-WORKER ['m.json']", proc.stdout)
        self.assertNotIn("uv", proc.stderr)

    def test_coordinator_branch_still_wants_uv(self) -> None:
        proc = self.run_dv("--list")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("`uv` is required", proc.stderr)


if __name__ == "__main__":
    unittest.main()
