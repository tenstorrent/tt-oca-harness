# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The cluster executor against fake scheduler commands: submit, poll, history, cancel and
reconcile for both drivers, the parsers against the observed output shapes, and the
coordinator running a real DUT's leaves through the fake scheduler and the real worker.

No scheduler is installed: ``fake_scheduler.py`` answers as ``bsub``/``bjobs``/``bhist``/
``bkill`` and ``sbatch``/``squeue``/``sacct``/``scontrol``/``scancel`` from a scenario file,
and a fake clock makes every grace window deterministic.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_scheduler  # noqa: E402
from runlib import cli  # noqa: E402
from runlib.config import load_executors  # noqa: E402
from runlib.executors import (  # noqa: E402
    CLUSTER_DEFAULT_LIMITS,
    DIALECTS,
    IMPLEMENTED_DRIVERS,
    build_executor,
    dispatch_blocker,
    executor_limits,
)
from runlib.executors.base import (  # noqa: E402
    JobHandle,
    JobObservation,
    JobState,
    LeafTask,
    ResourceRequest,
    task_identifier,
)
from runlib.executors.cluster import (  # noqa: E402
    CANCEL_POLL_SEC,
    QUERY_FAILURE_LIMIT,
    SUBMIT_FAILURE_LIMIT,
    CancelReply,
    ClusterError,
    ClusterExecutor,
    CommandResult,
    job_log_path,
    script_path,
)
from runlib.executors.lsf import LsfDialect  # noqa: E402
from runlib.executors.manifest import completion_path, manifest_path  # noqa: E402
from runlib.executors.slurm import SlurmDialect  # noqa: E402
from runlib.models import ConfigError  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[2]
FAKE_LEAF = TESTS_DIR / "fake_leaf.py"
FAKE_WORKER = TESTS_DIR / "fake_worker.py"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def command(stdout: str = "", stderr: str = "", rc: int | None = 0) -> CommandResult:
    return CommandResult(["x"], rc, stdout, stderr, 0.01, timed_out=rc is None)


class FakeSchedulerCase(unittest.TestCase):
    """A run directory, a fake scheduler on PATH, and a cluster executor over a fake clock."""

    driver = "lsf"

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix=f"cluster-{self.driver}-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.run_dir = self.tmp / "runs" / "r1"
        self.run_dir.mkdir(parents=True)
        self.state = self.tmp / "sched"
        self.bin = self.tmp / "bin"
        fake_scheduler.install(self.bin)
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "OCAH_FAKE_SCHEDULER": str(self.state),
        }
        self.clock = FakeClock()
        self.events: list[str] = []
        self.registry = load_executors(REPO_ROOT)

    def scenario(self, **tables: Any) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "scenario.json").write_text(json.dumps(tables), encoding="utf-8")

    def cfg(self, **overrides: Any) -> dict[str, Any]:
        table = dict(self.registry[self.driver])
        table["worker_argv"] = [sys.executable, str(FAKE_LEAF), "{manifest}"]
        table.update(overrides)
        return table

    def executor(self, cfg: dict[str, Any] | None = None, **limits: Any) -> ClusterExecutor:
        table = cfg or self.cfg()
        merged = {
            **executor_limits(table),
            "poll_interval_sec": 0.01,
            "artifact_grace_sec": 5.0,
            "cancel_grace_sec": 3.0,
            "command_timeout_sec": 1.0,
            **limits,
        }
        return ClusterExecutor(
            self.driver,
            table,
            DIALECTS[self.driver](),
            root=self.tmp,
            run_dir=self.run_dir,
            limits=merged,
            env=self.env,
            on_event=self.events.append,
            clock=self.clock,
            sleep=self.clock.sleep,
        )

    def task(
        self,
        leaf_id: int,
        item: str = "t_alpha",
        attempt: int = 0,
        resources: ResourceRequest | None = None,
    ) -> LeafTask:
        task_id = task_identifier("sim", leaf_id, attempt)
        leaf_dir = self.run_dir / item / f"seed_{leaf_id}" / f"attempt_{attempt}"
        manifest = manifest_path(self.run_dir, task_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "leaf_dir": str(leaf_dir),
                    "completion": str(completion_path(self.run_dir, task_id)),
                    "item": item,
                    "seed": leaf_id,
                    "attempt": attempt,
                }
            ),
            encoding="utf-8",
        )
        return LeafTask(
            task_id=task_id,
            leaf_id=leaf_id,
            stage="sim",
            item=item,
            seed=leaf_id,
            attempt=attempt,
            run_dir=self.run_dir,
            leaf_dir=leaf_dir,
            nest=True,
            resources=resources or ResourceRequest(),
            manifest_path=manifest,
        )

    def settle(
        self, executor: ClusterExecutor, handles: Sequence[JobHandle], rounds: int = 30
    ) -> tuple[dict[str, JobObservation], list[dict[str, JobObservation]]]:
        """Poll until every handle is terminal; every intermediate poll comes back too."""
        history: list[dict[str, JobObservation]] = []
        for _ in range(rounds):
            seen = executor.poll(handles)
            history.append(seen)
            if all(observation.state.terminal for observation in seen.values()):
                return seen, history
            executor.wait(handles, 1.0)
        self.fail(f"handles never settled: {[obs.state for obs in history[-1].values()]}")

    def calls(self, family: str | None = None) -> list[dict[str, Any]]:
        log = self.state / "calls.log"
        if not log.is_file():
            return []
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        if family is None:
            return rows
        names = {name for name, (_, kind) in fake_scheduler.COMMANDS.items() if kind == family}
        return [row for row in rows if row["command"] in names]

    def leaf_status(self, task: LeafTask, status: str) -> None:
        os.environ["FAKE_LEAF_STATUS"] = status
        self.addCleanup(os.environ.pop, "FAKE_LEAF_STATUS", None)
        self.env["FAKE_LEAF_STATUS"] = status


class ClusterExecutorTests(FakeSchedulerCase):
    """Runs once per driver through the subclasses at the bottom of the module."""

    def test_submit_poll_collect_passes_the_leaf_verdict_through(self) -> None:
        self.scenario(submit={"stderr_noise": True})
        executor = self.executor()
        tasks = [
            self.task(
                1, resources=ResourceRequest(queue="regress", cores=2, mem_mb=4096, walltime="1:30")
            ),
            self.task(2, item="t_beta"),
        ]
        handles = [executor.submit(task) for task in tasks]
        self.assertEqual([handle.native_job_id for handle in handles], ["1001", "1002"])
        self.assertTrue(all(handle.driver == self.driver for handle in handles))
        first = executor.poll(handles)
        self.assertEqual({obs.state for obs in first.values()}, {JobState.RUNNING})
        final, _ = self.settle(executor, handles)
        self.assertEqual({obs.state for obs in final.values()}, {JobState.SUCCEEDED})
        log = executor.executor_log.read_text(encoding="utf-8")
        self.assertIn(fake_scheduler.ESUB_NOISE, log)
        self.assertIn(fake_scheduler.ESUB_NOISE_UNSIZED, log)
        for task, handle in zip(tasks, handles):
            outcome = executor.collect(handle)
            assert outcome.result is not None
            self.assertEqual(outcome.result.status, "PASS")
            self.assertEqual(outcome.result.metadata["scheduler"]["job_id"], handle.native_job_id)
            self.assertEqual(outcome.result.metadata["scheduler"]["state"], "SUCCEEDED")
            self.assertEqual(
                outcome.result.artifacts["executor_log"],
                str(job_log_path(self.run_dir, task.task_id).relative_to(self.tmp)),
            )
            self.assertEqual(outcome.result_json, str(task.result_json.relative_to(self.tmp)))
            script = script_path(self.run_dir, task.task_id)
            self.assertTrue(os.access(script, os.X_OK))
            self.assertIn(str(task.manifest_path), script.read_text(encoding="utf-8"))
            self.assertIn("fake leaf", job_log_path(self.run_dir, task.task_id).read_text())
        submit = self.calls("submit")[0]["argv"]
        if self.driver == "lsf":
            self.assertEqual(
                submit[:9],
                ["bsub", "-q", "regress", "-n", "2", "-R", "rusage[mem=4096]", "-W", "90"],
            )
        else:
            self.assertEqual(
                submit[:6],
                [
                    "sbatch",
                    "--parsable",
                    "--partition=regress",
                    "--cpus-per-task=2",
                    "--mem=4096M",
                    "--time=01:30:00",
                ],
            )
        self.assertTrue(all(self.calls("submit")[1]["argv"][k] != "-q" for k in range(3)))
        log = executor.executor_log.read_text(encoding="utf-8")
        self.assertIn(" submit rc=0 ", log)
        self.assertIn(" query rc=", log)
        executor.close()

    def test_failed_leaf_grades_from_its_own_result(self) -> None:
        self.scenario()
        self.leaf_status(self.task(9), "FAIL")
        executor = self.executor()
        handle = executor.submit(self.task(3))
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.FAILED)
        self.assertEqual(
            final[handle.task_id].exit_code, 1, "from the query or the completion record"
        )
        outcome = executor.collect(handle)
        assert outcome.result is not None
        self.assertEqual(outcome.result.status, "FAIL")
        self.assertEqual(outcome.state, JobState.FAILED)

    def test_terminal_state_waits_for_the_result_within_the_grace(self) -> None:
        self.scenario(jobs={"default": {"states": ["PEND", "RUN", "DONE"], "run_script": False}})
        executor = self.executor(artifact_grace_sec=3.0)
        handle = executor.submit(self.task(4))
        final, history = self.settle(executor, [handle])
        waiting = [
            seen[handle.task_id]
            for seen in history
            if seen[handle.task_id].state is JobState.RECONCILING
        ]
        self.assertTrue(waiting, "a terminal job without a result is held as RECONCILING")
        self.assertIn("waiting for result.json", waiting[0].reason)
        self.assertEqual(final[handle.task_id].state, JobState.SUCCEEDED)
        self.assertIn("no result.json appeared within 3s", final[handle.task_id].reason)
        outcome = executor.collect(handle)
        self.assertIsNone(outcome.result)
        self.assertIn("no result.json", outcome.error)

    def test_vanished_job_that_left_a_result_reconciles_from_the_completion_record(self) -> None:
        self.scenario(jobs={"default": {"states": ["PEND", "RUN", "VANISH"]}})
        executor = self.executor()
        handle = executor.submit(self.task(5))
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.SUCCEEDED)
        self.assertIn("completion record", final[handle.task_id].reason)
        outcome = executor.collect(handle)
        assert outcome.result is not None
        self.assertEqual(outcome.result.status, "PASS")
        self.assertEqual(self.calls("history"), [], "artifacts settle a job before history runs")

    def test_vanished_job_without_a_result_settles_from_history(self) -> None:
        self.scenario(
            jobs={
                "default": {
                    "states": ["PEND", "RUN", "VANISH"],
                    "run_script": False,
                    "history": "TIMEOUT",
                }
            }
        )
        executor = self.executor()
        handle = executor.submit(self.task(6, resources=ResourceRequest(walltime="10")))
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.TIMED_OUT)
        self.assertEqual(len(self.calls("history")), 1, "history answered on its first call")
        outcome = executor.collect(handle)
        assert outcome.result is not None
        self.assertEqual(outcome.result.status, "TIMEOUT")
        self.assertIn("wall time expired", outcome.result.reason)
        self.assertEqual(outcome.result.metadata["scheduler"]["state"], "TIMED_OUT")

    def test_vanished_job_with_nothing_to_show_is_lost_after_the_grace(self) -> None:
        self.scenario(
            jobs={
                "default": {
                    "states": ["PEND", "RUN", "VANISH"],
                    "run_script": False,
                    "history": "none",
                }
            }
        )
        executor = self.executor(artifact_grace_sec=4.0)
        handle = executor.submit(self.task(7))
        final, history = self.settle(executor, [handle])
        reconciling = [
            seen for seen in history if seen[handle.task_id].state is JobState.RECONCILING
        ]
        self.assertGreaterEqual(len(reconciling), 4)
        self.assertEqual(final[handle.task_id].state, JobState.LOST)
        self.assertIn("no history record", final[handle.task_id].reason)
        outcome = executor.collect(handle)
        self.assertIsNone(outcome.result)
        self.assertEqual(outcome.state, JobState.LOST)

    def test_history_failure_keeps_reconciling_then_recovers(self) -> None:
        self.scenario(
            history={"fail_calls": [1, 2]},
            jobs={
                "default": {
                    "states": ["PEND", "RUN", "VANISH"],
                    "run_script": False,
                    "history": "KILLED",
                }
            },
        )
        executor = self.executor()
        handle = executor.submit(self.task(8))
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.CANCELLED)
        self.assertGreaterEqual(len(self.calls("history")), 3)

    def test_failed_query_retains_the_previous_state_and_backs_off(self) -> None:
        self.scenario(query={"fail_calls": [2, 3]})
        executor = self.executor()
        handle = executor.submit(self.task(10))
        running = executor.poll([handle])[handle.task_id]
        self.assertEqual(running.state, JobState.RUNNING)
        before = self.clock.now
        for _ in range(2):
            retained = executor.poll([handle])[handle.task_id]
            self.assertIs(retained, running, "a failed query changes nothing")
        executor.wait([handle], 1.0)
        self.assertEqual(self.clock.now - before, 4.0, "two failures quadruple the wait")
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.SUCCEEDED)
        self.assertTrue(any("query failed (2/" in event for event in self.events))

    def test_consecutive_query_failures_abort_the_run(self) -> None:
        self.scenario(query={"fail_calls": list(range(1, QUERY_FAILURE_LIMIT + 1))})
        executor = self.executor()
        handle = executor.submit(self.task(11))
        for _ in range(QUERY_FAILURE_LIMIT - 1):
            self.assertEqual(executor.poll([handle])[handle.task_id].state, JobState.QUEUED)
        with self.assertRaises(ClusterError) as ctx:
            executor.poll([handle])
        self.assertIn("consecutive", str(ctx.exception))
        confirmed = executor.cancel([handle], grace_sec=2.0)
        self.assertTrue(confirmed[handle.task_id])

    def test_hung_query_counts_as_a_failure(self) -> None:
        self.scenario(query={"hang_calls": [1], "hang_sec": 2.0})
        executor = self.executor(command_timeout_sec=0.3)
        handle = executor.submit(self.task(12))
        self.assertEqual(executor.poll([handle])[handle.task_id].state, JobState.QUEUED)
        self.assertIn(" query timeout ", executor.executor_log.read_text(encoding="utf-8"))
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.SUCCEEDED)

    def test_submission_refusal_grades_the_attempt_and_repeats_abort(self) -> None:
        self.scenario(submit={"reject_queue": "short"})
        executor = self.executor()
        refused = self.task(13, resources=ResourceRequest(queue="short"))
        handle = executor.submit(refused)
        self.assertEqual(handle.native_job_id, "")
        seen = executor.poll([handle])[handle.task_id]
        self.assertEqual(seen.state, JobState.FAILED)
        self.assertIn("submission failed", seen.reason)
        outcome = executor.collect(handle)
        self.assertIsNone(outcome.result)
        self.assertIn("submission failed", outcome.error)
        self.assertEqual(self.calls("query"), [], "a refused submission needs no query")
        executor.submit(self.task(14, resources=ResourceRequest(queue="regress")))
        for leaf_id in range(20, 20 + SUBMIT_FAILURE_LIMIT - 1):
            executor.submit(self.task(leaf_id, resources=ResourceRequest(queue="short")))
        with self.assertRaises(ClusterError) as ctx:
            executor.submit(self.task(30, resources=ResourceRequest(queue="short")))
        self.assertIn(f"{SUBMIT_FAILURE_LIMIT} consecutive submissions", str(ctx.exception))

    def test_cancel_confirms_kills_and_records_what_it_cannot_confirm(self) -> None:
        self.scenario(
            jobs={
                "default": {"states": ["PEND", "RUN", "RUN", "RUN", "RUN", "RUN"]},
                "sim-000042": {"states": ["PEND", "RUN", "RUN", "RUN", "RUN"], "ignore_kill": True},
                "sim-000043": {"states": ["PEND", "RUN"], "unknown_to_kill": True},
                "sim-000044": {"states": ["PEND", "RUN", "AUTO"]},
            }
        )
        executor = self.executor()
        killed = executor.submit(self.task(41))
        ignored = executor.submit(self.task(42))
        unknown = executor.submit(self.task(43))
        finished = executor.submit(self.task(44))
        handles = [killed, ignored, unknown, finished]
        executor.poll(handles)
        executor.poll(handles)
        confirmed = executor.cancel(handles, grace_sec=2.5)
        self.assertEqual(
            confirmed,
            {
                killed.task_id: True,
                ignored.task_id: False,
                unknown.task_id: False,
                finished.task_id: True,
            },
        )
        self.assertEqual(executor.poll([killed])[killed.task_id].state, JobState.CANCELLED)
        record = json.loads(executor.unconfirmed_cancels.read_text(encoding="utf-8"))
        self.assertEqual(
            {(job["task_id"], job["cancel_reply"]) for job in record["jobs"]},
            {(ignored.task_id, "requested"), (unknown.task_id, "unknown")},
        )
        self.assertTrue(any("unconfirmed" in event for event in self.events))
        cancel_argv = self.calls("cancel")[0]["argv"]
        self.assertEqual(cancel_argv[0], "bkill" if self.driver == "lsf" else "scancel")
        # A job the executor already saw finish is not killed again.
        self.assertEqual(set(cancel_argv[1:]), {"1001", "1002", "1003"})

    def test_cancel_never_raises_when_the_scheduler_is_down(self) -> None:
        self.scenario(cancel={"fail_calls": [1]}, query={"fail_calls": [2, 3, 4, 5, 6]})
        executor = self.executor()
        handle = executor.submit(self.task(50))
        executor.poll([handle])
        confirmed = executor.cancel([handle], grace_sec=1.0)
        self.assertEqual(confirmed, {handle.task_id: False})
        self.assertTrue(executor.unconfirmed_cancels.is_file())

    def test_cancel_stops_waiting_when_asked(self) -> None:
        self.scenario(
            jobs={"default": {"states": ["PEND", "RUN", "RUN", "RUN"], "ignore_kill": True}}
        )
        executor = self.executor()
        handle = executor.submit(self.task(46))
        executor.poll([handle])
        stop = threading.Event()
        stop.set()
        started = self.clock.now
        confirmed = executor.cancel([handle], grace_sec=100.0, stop=stop)
        self.assertEqual(confirmed, {handle.task_id: False})
        # One confirmation query, then the stop ends the wait before any grace sleep.
        self.assertLess(self.clock.now - started, CANCEL_POLL_SEC)
        self.assertEqual(len(self.calls("cancel")), 1)
        record = json.loads(executor.unconfirmed_cancels.read_text(encoding="utf-8"))
        self.assertEqual([job["task_id"] for job in record["jobs"]], [handle.task_id])

    def test_debug_and_retry_attempts_get_their_own_jobs(self) -> None:
        self.scenario()
        executor = self.executor()
        first = executor.submit(self.task(60, attempt=0))
        second = executor.submit(self.task(60, attempt=1))
        self.assertNotEqual(first.task_id, second.task_id)
        final, _ = self.settle(executor, [first, second])
        self.assertEqual({obs.state for obs in final.values()}, {JobState.SUCCEEDED})
        self.assertTrue(script_path(self.run_dir, first.task_id).is_file())
        self.assertTrue(script_path(self.run_dir, second.task_id).is_file())

    def test_env_passthrough_lands_in_the_job_script(self) -> None:
        self.scenario()
        self.env["OCAH_TEST_TOKEN"] = "forwarded value"
        executor = self.executor(
            self.cfg(env_passthrough=["PATH", "OCAH_TEST_TOKEN", "OCAH_UNSET_VAR"])
        )
        handle = executor.submit(self.task(70))
        text = script_path(self.run_dir, handle.task_id).read_text(encoding="utf-8")
        self.assertIn("export OCAH_TEST_TOKEN='forwarded value'", text)
        self.assertIn(
            f"export PATH={self.env['PATH']!r}".replace('"', "'")[: len("export PATH=")], text
        )
        self.assertNotIn("OCAH_UNSET_VAR", text)
        self.assertIn(f"cd {self.tmp}", text)
        self.assertTrue(text.rstrip().splitlines()[-1].startswith("exec "))

    def test_build_executor_sources_the_hook_and_checks_binaries(self) -> None:
        hook = self.tmp / "sched.env"
        hook.write_text(
            f"export PATH={self.bin}:$PATH\nexport OCAH_FAKE_SCHEDULER={self.state}\n",
            encoding="utf-8",
        )
        table = self.cfg(setup_hook=str(hook))
        bare = os.pathsep.join(["/nonexistent-bin", "/usr/bin", "/bin"])
        with mock.patch.dict(os.environ, {"PATH": bare, "OCAH_FAKE_SCHEDULER": ""}):
            built = build_executor(
                self.driver,
                table,
                runner=lambda task: None,
                max_workers=4,
                root=self.tmp,
                run_dir=self.run_dir,
            )
            self.assertIsInstance(built, ClusterExecutor)
            self.assertEqual(built.submit_batch_size, CLUSTER_DEFAULT_LIMITS["submit_batch_size"])
            with self.assertRaises(ConfigError) as ctx:
                build_executor(
                    self.driver,
                    self.cfg(),
                    runner=lambda task: None,
                    max_workers=4,
                    root=self.tmp,
                    run_dir=self.run_dir,
                )
            self.assertIn("cannot find", str(ctx.exception))
        with self.assertRaises(ConfigError):
            build_executor(self.driver, self.cfg(), runner=lambda task: None, max_workers=1)
        self.assertIsNone(dispatch_blocker(self.driver, self.cfg()))
        blocker = dispatch_blocker(self.driver, self.cfg(history_parser="no_such_parser"))
        assert blocker is not None
        self.assertIn("history_parser", blocker)


class LsfExecutorTest(ClusterExecutorTests):
    driver = "lsf"


class SlurmExecutorTest(ClusterExecutorTests):
    driver = "slurm"

    def test_strict_multi_id_query_falls_back_to_one_id_at_a_time(self) -> None:
        self.scenario(
            query={"strict_multi_id": True, "min_job_age_queries": 0},
            jobs={
                "default": {"states": ["PEND", "RUN", "AUTO"]},
                "sim-000082": {"states": ["PEND", "PEND", "PEND", "RUN", "AUTO"]},
            },
        )
        executor = self.executor()
        quick = executor.submit(self.task(81))
        slow = executor.submit(self.task(82))
        final, _ = self.settle(executor, [quick, slow])
        self.assertEqual({obs.state for obs in final.values()}, {JobState.SUCCEEDED})
        per_id = [
            row for row in self.calls("query") if any(part == "--jobs=1001" for part in row["argv"])
        ]
        self.assertTrue(per_id, "the batched squeue failed and was retried per id")

    def test_sacct_unavailable_then_scontrol_history(self) -> None:
        self.scenario(
            history={"unavailable": True},
            jobs={"default": {"states": ["PEND", "RUN", "VANISH"], "run_script": False}},
        )
        executor = self.executor(artifact_grace_sec=3.0)
        handle = executor.submit(self.task(90))
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.LOST)
        self.scenario(
            jobs={
                "default": {
                    "states": ["PEND", "RUN", "VANISH"],
                    "run_script": False,
                    "history": "DONE",
                }
            }
        )
        table = self.cfg(
            history_argv=["scontrol", "show", "job", "{job_id}"], history_parser="slurm_scontrol"
        )
        executor = self.executor(table)
        handle = executor.submit(self.task(91))
        final, _ = self.settle(executor, [handle])
        self.assertEqual(final[handle.task_id].state, JobState.SUCCEEDED)
        self.assertEqual(self.calls("history")[-1]["argv"][:3], ["scontrol", "show", "job"])


class LsfParserTest(unittest.TestCase):
    """The observed LSF output shapes."""

    dialect = LsfDialect()

    def test_submit_parses_stdout_only(self) -> None:
        noisy = command(
            "Job <4711> is submitted to queue <regress>.\n", "*** INFO *** memory hard limit 32G\n"
        )
        outcome = self.dialect.parse_submit(noisy)
        self.assertEqual((outcome.job_id, outcome.queue), ("4711", "regress"))
        default = command("Job <12> is submitted to default queue <normal>.\n")
        self.assertEqual(self.dialect.parse_submit(default).job_id, "12")
        refused = command("", "short: User cannot use the queue. Job not submitted.\n", 255)
        self.assertIsNone(self.dialect.parse_submit(refused).job_id)
        self.assertIn("cannot use the queue", self.dialect.parse_submit(refused).error)

    def test_bjobs_json_records(self) -> None:
        payload = {
            "COMMAND": "bjobs",
            "JOBS": 5,
            "RECORDS": [
                {
                    "JOBID": "1",
                    "STAT": "PEND",
                    "EXIT_CODE": "",
                    "EXIT_REASON": "",
                    "PEND_REASON": "New job is waiting for scheduling;",
                },
                {"JOBID": "2", "STAT": "RUN", "EXIT_CODE": "", "EXIT_REASON": ""},
                {
                    "JOBID": "3",
                    "STAT": "EXIT",
                    "EXIT_CODE": "",
                    "EXIT_REASON": "TERM_OWNER: job killed by owner.",
                },
                {"JOBID": "4", "STAT": "EXIT", "EXIT_CODE": "3", "EXIT_REASON": ""},
                {
                    "JOBID": "5",
                    "STAT": "EXIT",
                    "EXIT_CODE": "",
                    "EXIT_REASON": "TERM_RUNLIMIT: job killed after reaching LSF run time limit.",
                },
                {"JOBID": "6", "STAT": "DONE", "EXIT_CODE": "", "EXIT_REASON": ""},
                {
                    "JOBID": "7",
                    "STAT": "EXIT",
                    "EXIT_CODE": "",
                    "EXIT_REASON": "TERM_MEMLIMIT: job killed after reaching LSF memory usage limit.",
                },
                {"JOBID": "8", "STAT": "UNKWN", "EXIT_CODE": "", "EXIT_REASON": ""},
                {"JOBID": "9", "ERROR": "Job <9> is not found"},
            ],
        }
        ids = [str(index) for index in range(1, 11)]
        outcome = self.dialect.parse_query(command(json.dumps(payload)), ids)
        states = {job_id: obs.state for job_id, obs in outcome.observations.items()}
        self.assertEqual(
            states,
            {
                "1": JobState.QUEUED,
                "2": JobState.RUNNING,
                "3": JobState.CANCELLED,
                "4": JobState.FAILED,
                "5": JobState.TIMED_OUT,
                "6": JobState.SUCCEEDED,
                "7": JobState.FAILED,
                "8": JobState.RECONCILING,
            },
        )
        self.assertEqual(outcome.observations["4"].exit_code, 3)
        self.assertEqual(outcome.observations["6"].exit_code, 0)
        self.assertIn("waiting for scheduling", outcome.observations["1"].reason)
        self.assertEqual(outcome.missing, {"9", "10"})
        self.assertFalse(outcome.failed)
        down = self.dialect.parse_query(command("", "LSF is down. Please wait ...\n", 255), ["1"])
        self.assertEqual(down.failed, {"1"})

    def test_bhist_long_blocks(self) -> None:
        text = textwrap.dedent(
            """
            Job <100>, Job Name <ocah.r.sim-000001-a0>, User <u>, Project <default>, Command <x.sh>
            Fri Sep 19 11:10:05: Submitted from host <h>, to Queue <regress>, CWD <$HOME>;
            Fri Sep 19 11:12:00: Dispatched 1 Task(s) on Host(s) <n1>, Allocated 1 Slot(s) on Host(s) <n1>;
            Fri Sep 19 11:12:00: Starting (Pid 123);
            Fri Sep 19 11:12:01: Running with execution home <$HOME>, Execution CWD <$HOME>, Execution Pid <123>;
            Fri Sep 19 11:20:00: Done successfully. The CPU time used is 3.2 seconds;

            Summary of time in seconds spent in various states by  Fri Sep 19 11:20:00
              PEND     PSUSP    RUN      USUSP    SSUSP    UNKWN    TOTAL
              115      0        480      0        0        0        595

            Job <101>, Job Name <ocah.r.sim-000002-a0>, User <u>, Project <default>, Command <y.sh>
            Fri Sep 19 11:10:05: Submitted from host <h>, to Queue <regress>, CWD <$HOME>;
            Fri Sep 19 11:12:00: Starting (Pid 124);
            Fri Sep 19 11:30:00: Exited with exit code 3. The CPU time used is 900.2 seconds;

            Job <102>, Job Name <ocah.r.sim-000003-a0>, User <u>, Project <default>, Command <z.sh>
            Fri Sep 19 11:10:05: Submitted from host <h>, to Queue <regress>, CWD <$HOME>;
            Fri Sep 19 11:11:00: Signal <KILL> requested by user or administrator <u>;
            Fri Sep 19 11:11:00: Exited by signal 9. The CPU time used is 0.0 seconds;
            Fri Sep 19 11:11:00: Completed <exit>; TERM_OWNER: job killed by owner;

            Job <103>, Job Name <ocah.r.sim-000004-a0>, User <u>, Project <default>, Command <w.sh>
            Fri Sep 19 11:10:05: Submitted from host <h>, to Queue <regress>, CWD <$HOME>;
            Fri Sep 19 13:10:05: Completed <exit>; TERM_RUNLIMIT: job killed after reaching LSF run time limit;
            """
        )
        outcome = self.dialect.parse_bhist_long(command(text), ["100", "101", "102", "103", "104"])
        states = {
            job_id: (obs.state, obs.exit_code) for job_id, obs in outcome.observations.items()
        }
        self.assertEqual(
            states,
            {
                "100": (JobState.SUCCEEDED, 0),
                "101": (JobState.FAILED, 3),
                "102": (JobState.CANCELLED, None),
                "103": (JobState.TIMED_OUT, None),
            },
        )
        self.assertEqual(outcome.missing, {"104"})
        none = self.dialect.parse_bhist_long(command("No matching job found\n", "", 255), ["5"])
        self.assertEqual(none.missing, {"5"})
        self.assertFalse(none.failed)

    def test_bkill_replies(self) -> None:
        result = command(
            "Job <1> is being terminated\nJob <2>: Job has already finished\nJob <3>: No matching job found\n",
            "",
            255,
        )
        replies = self.dialect.parse_cancel(result, ["1", "2", "3", "4"])
        self.assertEqual(
            replies,
            {
                "1": CancelReply.REQUESTED,
                "2": CancelReply.FINISHED,
                "3": CancelReply.UNKNOWN,
                "4": CancelReply.UNKNOWN,
            },
        )


class SlurmParserTest(unittest.TestCase):
    """The observed Slurm output shapes."""

    dialect = SlurmDialect()

    def test_submit_forms(self) -> None:
        self.assertEqual(self.dialect.parse_submit(command("17\n")).job_id, "17")
        federated = self.dialect.parse_submit(command("17;cluster2\n"))
        self.assertEqual((federated.job_id, federated.cluster), ("17", "cluster2"))
        self.assertEqual(self.dialect.parse_submit(command("Submitted batch job 5\n")).job_id, "5")
        refused = command(
            "",
            "sbatch: error: invalid partition specified: nope\n"
            "sbatch: error: Batch job submission failed: Invalid partition name specified\n",
            1,
        )
        outcome = self.dialect.parse_submit(refused)
        self.assertIsNone(outcome.job_id)
        self.assertIn("Invalid partition", outcome.error)

    def test_squeue_lines_and_failures(self) -> None:
        text = "1|RUNNING|None\n4_2|PENDING|JobArrayTaskLimit\n7|COMPLETED|None\n8|CANCELLED|None\n"
        outcome = self.dialect.parse_query(command(text), ["1", "4", "7", "8", "9"])
        states = {job_id: obs.state for job_id, obs in outcome.observations.items()}
        self.assertEqual(
            states,
            {
                "1": JobState.RUNNING,
                "4": JobState.QUEUED,
                "7": JobState.SUCCEEDED,
                "8": JobState.CANCELLED,
            },
        )
        self.assertEqual(outcome.observations["4"].reason, "JobArrayTaskLimit")
        self.assertEqual(outcome.missing, {"9"})
        invalid = command("", "slurm_load_jobs error: Invalid job id specified\n", 1)
        self.assertEqual(self.dialect.parse_query(invalid, ["9"]).missing, {"9"})
        self.assertEqual(self.dialect.parse_query(invalid, ["9", "10"]).failed, {"9", "10"})
        self.assertTrue(self.dialect.retry_failed_query_per_id)

    def test_sacct_and_scontrol(self) -> None:
        text = "10|COMPLETED|0:0\n10.batch|COMPLETED|0:0\n11|FAILED|3:0\n12|CANCELLED by 1000|0:15\n13|TIMEOUT|0:0\n"
        outcome = self.dialect.parse_sacct(command(text), ["10", "11", "12", "13", "14"])
        self.assertEqual(
            {job_id: (obs.state, obs.exit_code) for job_id, obs in outcome.observations.items()},
            {
                "10": (JobState.SUCCEEDED, 0),
                "11": (JobState.FAILED, 3),
                "12": (JobState.CANCELLED, 0),
                "13": (JobState.TIMED_OUT, 0),
            },
        )
        self.assertIn("CANCELLED by 1000", outcome.observations["12"].reason)
        self.assertEqual(outcome.missing, {"14"})
        disabled = command("", "sacct: error: Slurm accounting storage is disabled\n", 1)
        self.assertEqual(self.dialect.parse_sacct(disabled, ["10"]).failed, {"10"})
        block = (
            "JobId=7 JobName=ocah_ok\n   UserId=u(1000) GroupId=u(1000) MCS_label=N/A\n"
            "   JobState=FAILED Reason=NonZeroExitCode Dependency=(null)\n   ExitCode=3:0\n"
        )
        seen = self.dialect.parse_scontrol(command(block), ["7"]).observations["7"]
        self.assertEqual(
            (seen.state, seen.exit_code, seen.reason), (JobState.FAILED, 3, "NonZeroExitCode")
        )
        aged = command("", "slurm_load_jobs error: Invalid job id specified\n", 1)
        self.assertEqual(self.dialect.parse_scontrol(aged, ["7"]).missing, {"7"})

    def test_scancel_replies(self) -> None:
        result = command(
            "", "scancel: error: Kill job error on job id 999: Invalid job id specified\n", 0
        )
        self.assertEqual(
            self.dialect.parse_cancel(result, ["1", "999"]),
            {"1": CancelReply.REQUESTED, "999": CancelReply.UNKNOWN},
        )


class DriverTableTest(unittest.TestCase):
    def test_both_checked_in_drivers_dispatch(self) -> None:
        self.assertEqual(set(IMPLEMENTED_DRIVERS), {"local", "lsf", "slurm"})
        self.assertEqual(set(DIALECTS), {"lsf", "slurm"})
        executors = load_executors(REPO_ROOT)
        for name in ("lsf", "slurm"):
            self.assertIsNone(dispatch_blocker(name, executors[name]))
            dialect = DIALECTS[executors[name]["driver"]]()
            self.assertIn(executors[name]["history_parser"], dialect.history_parsers)


class CoordinatorTest(unittest.TestCase):
    """`run_dv.py` driving a real DUT's leaves through the fake scheduler and the real worker."""

    driver = "lsf"
    dut = "dtp"

    @classmethod
    def setUpClass(cls) -> None:
        from runlib.config import load_test_catalog
        from runlib.duts import resolve_dut

        cls.items = list(load_test_catalog(resolve_dut(REPO_ROOT, cls.dut), REPO_ROOT).tests)[:2]

    def setUp(self) -> None:
        build = REPO_ROOT / "build"
        build.mkdir(exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="test-cluster-run-", dir=build)).resolve()
        if not os.environ.get("OCAH_TEST_KEEP"):
            self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.run_dir = self.tmp / "run"
        self.state = self.tmp / "sched"
        self.bin = self.tmp / "bin"
        fake_scheduler.install(self.bin)
        # The coordinator checks the selected simulator is on PATH before dispatching; no leaf
        # runs it here, so a shim that answers the version probe stands in for it.
        shim = self.bin / "verilator"
        shim.write_text(
            '#!/bin/sh\necho "Verilator 5.036 2025-04-05 rev v5.036"\n', encoding="utf-8"
        )
        shim.chmod(0o755)
        (self.tmp / "sched.env").write_text(
            f"export PATH={self.bin}:$PATH\nexport OCAH_FAKE_SCHEDULER={self.state}\n",
            encoding="utf-8",
        )
        self.site = self.tmp / "site.local.toml"
        self.write_site()

    def write_site(self, **limits: float) -> None:
        merged = {
            "poll_interval_sec": 0.1,
            "artifact_grace_sec": 5,
            "cancel_grace_sec": 2,
            "submit_batch_size": 1,
            **limits,
        }
        limit_lines = "\n".join(f"{name} = {value}" for name, value in merged.items())
        self.site.write_text(
            textwrap.dedent(
                f"""
                schema_version = 1
                [executors.{self.driver}]
                worker_argv = ["{sys.executable}", "{FAKE_WORKER}", "{{manifest}}"]
                setup_hook = "sched.env"
                defaults = {{ queue = "regress", cores = 1, mem_mb = 2048, walltime = "30" }}
                [executors.{self.driver}.limits]
                """
            )
            + limit_lines
            + "\n",
            encoding="utf-8",
        )

    def scenario(self, **tables: Any) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "scenario.json").write_text(json.dumps(tables), encoding="utf-8")

    def calls(self) -> list[dict[str, Any]]:
        log = self.state / "calls.log"
        if not log.is_file():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def signal_after_submits(
        self, count: int, *, signum: int = signal.SIGINT, repeat: int = 1, gap_sec: float = 1.0
    ) -> threading.Thread:
        """Send ``signum`` to this process once the fake scheduler has seen ``count`` submits.

        The coordinator installs its handler before the first submission, so the signal
        always reaches the run and never the test.
        """
        log = self.state / "calls.log"

        def fire() -> None:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                seen = 0
                if log.is_file():
                    for line in log.read_text(encoding="utf-8").splitlines():
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if row.get("command") in {"bsub", "sbatch"}:
                            seen += 1
                if seen >= count:
                    break
                time.sleep(0.05)
            for index in range(repeat):
                if index:
                    time.sleep(gap_sec)
                os.kill(os.getpid(), signum)

        thread = threading.Thread(target=fire, daemon=True)
        thread.start()
        return thread

    def run_dv(
        self, *extra: str, statuses: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        argv = [
            "--dut",
            self.dut,
            "--items",
            *self.items,
            "--stage",
            "sim",
            "--executor",
            self.driver,
            "--sim-jobs",
            "2",
            "--run-dir",
            str(self.run_dir),
            "--ui",
            "plain",
            *extra,
        ]
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "OCAH_DV_SITE": str(self.site),
            "FAKE_WORKER_STATUS": json.dumps(statuses or {}),
            "OCAH_FAKE_SCHEDULER": str(self.state),
        }
        original = cli.parse_args

        def prebuilt(argv: list[str] | None = None) -> Any:
            parsed = original(argv)
            # The verilator model a parallel cocotb run builds first is not part of dispatch.
            parsed._cocotb_prebuilt_targets = {"default"}
            return parsed

        console = io.StringIO()
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(cli, "parse_args", prebuilt),
            redirect_stdout(console),
            redirect_stderr(console),
        ):
            code = cli.main(argv)
        result_json = self.run_dir / "result.json"
        self.assertTrue(result_json.is_file(), f"exit {code}; console:\n{console.getvalue()}")
        return code, json.loads(result_json.read_text(encoding="utf-8"))

    def leaves(self, summary: dict[str, Any]) -> list[dict[str, Any]]:
        return [stage for stage in summary["stages"] if stage["name"] == "sim"]

    def leaf_statuses(self, summary: dict[str, Any]) -> dict[str, str]:
        return {leaf["item"]: leaf["status"] for leaf in self.leaves(summary)}

    def test_leaves_run_as_jobs_and_grade_from_their_results(self) -> None:
        self.scenario(submit={"stderr_noise": True})
        code, summary = self.run_dv()
        self.assertEqual(code, 0, summary.get("status"))
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(self.leaf_statuses(summary), {item: "PASS" for item in self.items})
        self.assertEqual(summary["tests"]["leaves_run"], 2)
        for leaf in self.leaves(summary):
            self.assertEqual(leaf["metadata"]["scheduler"]["driver"], self.driver)
            self.assertTrue(leaf["metadata"]["scheduler"]["job_id"])
            self.assertTrue(leaf["artifacts"]["executor_log"].endswith(".log"))
        jobs = sorted((self.run_dir / "stages" / "regress" / "jobs").glob("sim-*.json"))
        self.assertEqual(len([p for p in jobs if not p.name.endswith(".done.json")]), 2)
        self.assertEqual(len([p for p in jobs if p.name.endswith(".done.json")]), 2)
        scripts = list((self.run_dir / "stages" / "regress" / "scripts").glob("*.sh"))
        self.assertEqual(len(scripts), 2)
        log = (self.run_dir / "stages" / "regress" / "logs" / "executor.log").read_text(
            encoding="utf-8"
        )
        self.assertEqual(log.count(" submit rc=0 "), 2)
        calls = [json.loads(line) for line in (self.state / "calls.log").read_text().splitlines()]
        submits = [row for row in calls if row["command"] in {"bsub", "sbatch"}]
        self.assertIn("regress", " ".join(submits[0]["argv"]))
        self.assertTrue(any(row["command"] in {"bjobs", "squeue"} for row in calls))
        self.assertFalse(any(row["command"] in {"bkill", "scancel"} for row in calls))

    def test_retry_resubmits_a_failed_leaf_as_a_new_job(self) -> None:
        self.scenario()
        flaky = self.items[0]
        code, summary = self.run_dv("--retry", "1", statuses={flaky: ["FAIL", "PASS"]})
        self.assertEqual(code, 0, summary.get("status"))
        self.assertEqual(summary["status"], "PASS")
        manifests = sorted(
            p.name
            for p in (self.run_dir / "stages" / "regress" / "jobs").glob("sim-*-a*.json")
            if ".done" not in p.name
        )
        self.assertEqual(len(manifests), 3, manifests)
        calls = [json.loads(line) for line in (self.state / "calls.log").read_text().splitlines()]
        self.assertEqual(len([row for row in calls if row["command"] in {"bsub", "sbatch"}]), 3)

    def test_a_lost_job_grades_environment_error(self) -> None:
        self.scenario(
            jobs={
                "default": {"states": ["PEND", "RUN", "AUTO"]},
                "sim-000001": {
                    "states": ["PEND", "RUN", "VANISH"],
                    "run_script": False,
                    "history": "none",
                },
            }
        )
        code, summary = self.run_dv()
        self.assertEqual(code, 2, summary.get("status"))
        statuses = self.leaf_statuses(summary)
        self.assertEqual(sorted(statuses.values()), ["ERROR", "PASS"])
        lost = next(leaf for leaf in self.leaves(summary) if leaf["status"] == "ERROR")
        self.assertIn("environment_error", lost["reason"])
        self.assertIn("lost", lost["reason"])

    def test_a_wave_debug_rerun_is_its_own_job(self) -> None:
        self.scenario()
        failing = self.items[0]
        code, summary = self.run_dv("--waves-on-fail", "fst", statuses={failing: ["FAIL", "PASS"]})
        self.assertEqual(code, 1, summary.get("status"))
        self.assertEqual(summary["status"], "FAIL")
        leaf = next(leaf for leaf in self.leaves(summary) if leaf["item"] == failing)
        self.assertEqual(leaf["status"], "FAIL")
        debug = leaf["metadata"]["wave_debug"]
        self.assertTrue(debug["debug_only"])
        self.assertFalse(debug["status_affects_final_result"])
        graded_job = leaf["metadata"]["scheduler"]["job_id"]
        debug_job = debug["metadata"]["scheduler"]["job_id"]
        self.assertTrue(graded_job)
        self.assertTrue(debug_job)
        self.assertNotEqual(graded_job, debug_job)
        self.assertEqual(debug["metadata"]["scheduler"]["driver"], self.driver)
        manifests = sorted(
            p.name
            for p in (self.run_dir / "stages" / "regress" / "jobs").glob("sim-*.json")
            if ".done" not in p.name
        )
        self.assertEqual(
            [m for m in manifests if m.endswith("-debug.json")], ["sim-000000-a1-debug.json"]
        )
        self.assertEqual(
            len([row for row in self.calls() if row["command"] in {"bsub", "sbatch"}]), 3
        )

    # Jobs that stay RUN long past every grace in these tests, then finish on their own so a
    # broken interruption path fails the test instead of hanging it.
    LONG_RUNNING = {"states": ["PEND", *(["RUN"] * 600), "DONE"], "run_script": False}

    def test_interruption_cancels_the_jobs_and_records_them(self) -> None:
        self.scenario(
            jobs={
                "default": self.LONG_RUNNING,
                "sim-000001": {**self.LONG_RUNNING, "ignore_kill": True},
            }
        )
        watcher = self.signal_after_submits(2)
        code, summary = self.run_dv()
        watcher.join(timeout=5)
        self.assertEqual(code, 128 + signal.SIGINT)
        self.assertEqual(summary["status"], "ERROR")
        interruption = summary["interruption"]
        self.assertEqual(interruption["kind"], "signal")
        self.assertEqual(interruption["signals"], ["SIGINT"])
        cancellation = interruption["cancellation"]
        self.assertEqual(cancellation["driver"], self.driver)
        self.assertEqual((cancellation["requested"], cancellation["confirmed"]), (2, 1))
        self.assertFalse(cancellation["wait_cut_short"])
        (unconfirmed,) = cancellation["unconfirmed"]
        self.assertEqual(unconfirmed["task_id"], "sim-000001-a0")
        self.assertEqual(unconfirmed["item"], self.items[1])
        self.assertTrue(unconfirmed["job_id"])
        record = self.run_dir / "stages" / "regress" / "jobs" / "cancel-unconfirmed.json"
        self.assertTrue(record.is_file())
        self.assertTrue(cancellation["record"].endswith("jobs/cancel-unconfirmed.json"))
        progress = summary["progress"]
        self.assertEqual(progress["state"], "interrupted")
        self.assertEqual((progress["completed_count"], progress["interrupted_count"]), (0, 2))
        jobs = {}
        for leaf in progress["interrupted"]:
            (job,) = leaf["jobs"]
            self.assertEqual(job["driver"], self.driver)
            self.assertTrue(job["job_id"])
            self.assertFalse(job["debug_only"])
            jobs[job["task_id"]] = job
        self.assertEqual(
            {task_id: job["cancel_confirmed"] for task_id, job in jobs.items()},
            {"sim-000000-a0": True, "sim-000001-a0": False},
        )
        self.assertEqual(jobs["sim-000001-a0"]["job_id"], unconfirmed["job_id"])
        regression = json.loads(
            (self.run_dir / "stages" / "regress" / "regression.json").read_text(encoding="utf-8")
        )
        self.assertEqual(regression["interruption"]["cancellation"], cancellation)
        self.assertTrue((self.run_dir / "results" / "results.xml").is_file())
        cancels = [row for row in self.calls() if row["command"] in {"bkill", "scancel"}]
        self.assertEqual(len(cancels), 1)
        self.assertEqual(set(cancels[0]["argv"][1:]), {job["job_id"] for job in jobs.values()})

    def test_a_second_signal_ends_the_confirmation_wait(self) -> None:
        self.write_site(cancel_grace_sec=90)
        self.scenario(jobs={"default": {**self.LONG_RUNNING, "ignore_kill": True}})
        watcher = self.signal_after_submits(2, repeat=2, gap_sec=1.5)
        started = time.monotonic()
        code, summary = self.run_dv()
        watcher.join(timeout=5)
        self.assertLess(time.monotonic() - started, 45)
        self.assertEqual(code, 128 + signal.SIGINT)
        interruption = summary["interruption"]
        self.assertEqual(interruption["signals"], ["SIGINT", "SIGINT"])
        cancellation = interruption["cancellation"]
        self.assertTrue(cancellation["wait_cut_short"])
        self.assertEqual((cancellation["requested"], cancellation["confirmed"]), (2, 0))
        self.assertEqual(
            sorted(job["task_id"] for job in cancellation["unconfirmed"]),
            ["sim-000000-a0", "sim-000001-a0"],
        )
        self.assertEqual(summary["progress"]["interrupted_count"], 2)
        self.assertTrue(
            (self.run_dir / "stages" / "regress" / "jobs" / "cancel-unconfirmed.json").is_file()
        )


class SlurmCoordinatorTest(CoordinatorTest):
    driver = "slurm"


if __name__ == "__main__":
    unittest.main()
