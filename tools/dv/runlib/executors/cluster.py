# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The cluster executor: leaf attempts run as scheduler jobs.

Every scheduler interaction is one of the registry's argv templates rendered and run as a
subprocess: ``submit_argv`` once per attempt or once per job array, ``query_argv`` for a batch
of job ids on every poll, ``history_argv`` for ids absent from the live query, and
``cancel_argv`` on interruption. The executor reads no scheduler output itself; the driver's
:class:`SchedulerDialect` turns each command's output into normalized observations, so a site
changes flags in the registry while a driver changes parsing in code.

With ``arrays`` on, the first attempts of a stage go out as job arrays of at most
``array_chunk_size`` elements, one array per coordinator turn. Every element is its own
handle under the scheduler's element id (``1001[3]`` on LSF, ``1001_3`` on Slurm), so
polling, history, cancellation and collection never distinguish an element from a plain job;
retries and wave-debug reruns are plain jobs. The array's one script reads its element index
from the scheduler's environment and picks the matching manifest from the array's task list.

A job that leaves the live query without a terminal state is ``RECONCILING``: the completion
record and ``result.json`` the worker wrote settle it first, then the scheduler's history, and
only ``artifact_grace_sec`` without either makes it ``LOST``. A terminal state the scheduler
reports for a job that ran is likewise held until the leaf's ``result.json`` is visible or that
grace has passed, which absorbs a shared filesystem's lag. The verdict comes from that file
alone; scheduler state decides only whether an attempt is over.

A query that fails as a whole leaves every asked handle in its previous state and lengthens
the next wait; consecutive failures past a bound abort the run, as do consecutive submission
failures, so a scheduler that refuses everything stops a run instead of grading every leaf.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..models import StageResult
from ..paths import repo_rel
from ..results import write_result
from .base import (
    PLACEHOLDER_RE,
    ExecutionResult,
    Executor,
    JobHandle,
    JobObservation,
    JobState,
    LeafTask,
    now_iso,
    render_argv,
    result_from_fragment,
)
from .manifest import completion_path, jobs_dir

DEFAULT_WORKER_ARGV = [
    "{python}",
    "{repo_root}/tools/dv/run_dv.py",
    "--worker-manifest",
    "{manifest}",
]
EXECUTOR_LOG_NAME = "executor.log"
UNCONFIRMED_CANCELS_NAME = "cancel-unconfirmed.json"
ARRAY_TASKS_SUFFIX = ".tasks"
# Sentinels the array script replaces with the element's own values after quoting.
_ARRAY_TOKENS = {
    "manifest": ("@@OCAH_MANIFEST@@", "OCAH_MANIFEST"),
    "leaf_dir": ("@@OCAH_LEAF_DIR@@", "OCAH_LEAF_DIR"),
    "task_id": ("@@OCAH_TASK_ID@@", "OCAH_TASK_ID"),
}
# Consecutive failures that abort the run rather than grading one more attempt.
SUBMIT_FAILURE_LIMIT = 3
QUERY_FAILURE_LIMIT = 5
# Characters of a command's stdout and stderr kept in the executor log.
OUTPUT_LOG_LIMIT = 4000
CANCEL_POLL_SEC = 1.0
# Terminal states in which the worker ran to its own end and normally wrote a result.
_RESULT_BEARING = frozenset({JobState.SUCCEEDED, JobState.FAILED})


class ClusterError(RuntimeError):
    """The scheduler stopped answering in a way no single attempt can absorb."""


def scripts_dir(run_dir: Path) -> Path:
    return run_dir / "stages" / "regress" / "scripts"


def logs_dir(run_dir: Path) -> Path:
    return run_dir / "stages" / "regress" / "logs"


def script_path(run_dir: Path, task_id: str) -> Path:
    return scripts_dir(run_dir) / f"{task_id}.sh"


def job_log_path(run_dir: Path, task_id: str) -> Path:
    return logs_dir(run_dir) / f"{task_id}.log"


def array_tasks_path(run_dir: Path, label: str) -> Path:
    """The array's task list: one ``task_id<TAB>manifest<TAB>leaf_dir`` line per element."""
    return scripts_dir(run_dir) / f"{label}{ARRAY_TASKS_SUFFIX}"


@dataclass
class CommandResult:
    """One scheduler command as it ran."""

    argv: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    duration_sec: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def failure_text(self) -> str:
        """The most useful line to show for a command that did not do its job."""
        if self.timed_out:
            return f"timed out after {self.duration_sec:.0f}s"
        text = self.stderr.strip() or self.stdout.strip()
        if text:
            return text.splitlines()[-1][:300]
        return f"exit status {self.returncode}"


@dataclass
class SubmitOutcome:
    """What a submission command said: a job id, or why there is none."""

    job_id: str | None = None
    cluster: str | None = None
    queue: str | None = None
    error: str = ""


@dataclass
class QueryOutcome:
    """What one query or history command said about the ids it was asked for.

    An id is in exactly one place: ``observations`` when the scheduler described it,
    ``missing`` when the scheduler said it knows no such job, ``failed`` when the command
    answered nothing trustworthy about it.
    """

    observations: dict[str, JobObservation] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    error: str = ""

    def merge(self, other: QueryOutcome) -> None:
        self.observations.update(other.observations)
        self.missing |= other.missing
        self.failed |= other.failed
        if other.error:
            self.error = other.error


class CancelReply(str, Enum):
    """What a cancel command said about one id."""

    REQUESTED = "requested"
    FINISHED = "finished"
    UNKNOWN = "unknown"


class SchedulerDialect(ABC):
    """The driver half of a cluster executor: output parsing and the native state map."""

    driver: str
    # Names `history_parser` may select; each is a method on the dialect.
    history_parsers: Mapping[str, str] = {}
    # A scheduler that refuses a whole id list when one id is unknown answers per id instead.
    retry_failed_query_per_id: bool = False
    # The variable a job array element reads its index from, and the token the scheduler
    # expands to that index in an output path.
    array_index_env: str = ""
    array_log_token: str = ""
    # The submit placeholder that carries the array range, or None when the job name does.
    array_range_placeholder: str | None = None
    # Text the query template must contain for element records to be told apart, if any.
    array_query_marker: str = ""

    @property
    def supports_arrays(self) -> bool:
        return bool(self.array_index_env and self.array_log_token)

    def array_jobname(self, name: str, count: int) -> str:
        """The job name that submits ``count`` elements under ``name``."""
        return name

    def element_id(self, array_id: str, index: int) -> str:
        """The scheduler's id for element ``index`` (1-based) of array ``array_id``."""
        raise NotImplementedError

    @abstractmethod
    def parse_submit(self, result: CommandResult) -> SubmitOutcome: ...

    @abstractmethod
    def parse_query(self, result: CommandResult, job_ids: Sequence[str]) -> QueryOutcome: ...

    def parse_history(
        self, result: CommandResult, job_ids: Sequence[str], parser: str
    ) -> QueryOutcome:
        method = self.history_parsers.get(parser)
        if method is None:
            raise ClusterError(f"driver `{self.driver}` has no history parser `{parser}`")
        parse: Callable[[CommandResult, Sequence[str]], QueryOutcome] = getattr(self, method)
        return parse(result, job_ids)

    @abstractmethod
    def parse_cancel(
        self, result: CommandResult, job_ids: Sequence[str]
    ) -> dict[str, CancelReply]: ...


def whole_command_failed(result: CommandResult, job_ids: Iterable[str]) -> QueryOutcome:
    return QueryOutcome(failed=set(job_ids), error=result.failure_text)


def base_job_id(text: str) -> str:
    """The job id without an array-element suffix (``123[4]``, ``123_4``) or cluster."""
    token = text.strip().split(";")[0]
    for separator in ("[", "_", "."):
        if separator in token:
            token = token.split(separator)[0]
    return token


@dataclass
class _Tracked:
    task: LeafTask
    handle: JobHandle
    last: JobObservation
    script: Path | None
    joblog: Path
    array_label: str | None = None
    missing_since: float | None = None
    terminal_since: float | None = None
    history: JobObservation | None = None
    # The terminal observation ``poll`` reported; frozen from then on.
    settled: JobObservation | None = None


class ClusterExecutor(Executor):
    requires_manifest = True

    def __init__(
        self,
        name: str,
        cfg: Mapping[str, Any],
        dialect: SchedulerDialect,
        *,
        root: Path,
        run_dir: Path,
        limits: Mapping[str, Any],
        env: Mapping[str, str],
        on_event: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.driver = dialect.driver
        self._cfg = dict(cfg)
        self._dialect = dialect
        self._root = root
        self._run_dir = run_dir
        self._limits = dict(limits)
        self._env = dict(env)
        self._on_event = on_event
        self._clock = clock
        self._sleep = sleep
        self._tracked: dict[str, _Tracked] = {}
        self._submit_failures = 0
        self._query_failures = 0
        self._log_handle: Any = None
        self._passthrough = [str(name) for name in cfg.get("env_passthrough") or []]
        self._history_template = cfg.get("history_argv") or None
        self._history_parser = str(cfg.get("history_parser") or "")
        self._array_sequence = 0
        self._arrays_off_reason = self._arrays_blocker()
        self.submit_batch_size = (
            self.array_chunk_size
            if self._arrays_off_reason is None
            else int(self._limits["submit_batch_size"])
        )

    def _arrays_blocker(self) -> str | None:
        """Why this executor submits plain jobs only, or None when it may submit arrays."""
        if not self._cfg.get("arrays"):
            return "arrays are off in the registry"
        if not self._dialect.supports_arrays:
            return f"driver `{self.driver}` has no job-array support"
        placeholder = self._dialect.array_range_placeholder
        if placeholder and placeholder not in _template_placeholders(self._cfg["submit_argv"]):
            return f"submit_argv has no {{{placeholder}}} placeholder"
        marker = self._dialect.array_query_marker
        if marker and marker not in " ".join(str(part) for part in self._cfg["query_argv"]):
            return f"query_argv does not request `{marker}`"
        return None

    # -- configuration -------------------------------------------------------------------

    @property
    def max_in_flight(self) -> int:
        value = self._limits.get("max_in_flight")
        return int(value) if value else sys.maxsize

    @property
    def artifact_grace_sec(self) -> float:
        return float(self._limits["artifact_grace_sec"])

    @property
    def query_batch_size(self) -> int:
        return max(1, int(self._limits["query_batch_size"]))

    @property
    def command_timeout_sec(self) -> float:
        return float(self._limits["command_timeout_sec"])

    @property
    def array_chunk_size(self) -> int:
        return max(1, int(self._limits.get("array_chunk_size") or 1))

    @property
    def arrays_enabled(self) -> bool:
        return self._arrays_off_reason is None

    @property
    def executor_log(self) -> Path:
        return logs_dir(self._run_dir) / EXECUTOR_LOG_NAME

    @property
    def unconfirmed_cancels(self) -> Path:
        return jobs_dir(self._run_dir) / UNCONFIRMED_CANCELS_NAME

    # -- submit ---------------------------------------------------------------------------

    def submit(self, task: LeafTask) -> JobHandle:
        if task.manifest_path is None:
            raise ClusterError(f"{task.task_id}: no manifest was written for this attempt")
        script = self._write_script(task)
        joblog = job_log_path(self._run_dir, task.task_id)
        joblog.parent.mkdir(parents=True, exist_ok=True)
        values = {
            **task.resources.placeholders(),
            "jobname": self._job_name(task),
            "joblog": str(joblog),
            "script": str(script),
            "manifest": str(task.manifest_path),
            "python": sys.executable,
            "run_dir": str(self._run_dir),
            "repo_root": str(self._root),
            "leaf_dir": str(task.leaf_dir),
            "task_id": task.task_id,
            "executor": self.name,
        }
        template = self._cfg["submit_argv"]
        if task.is_build and self._cfg.get("build_submit_argv"):
            template = self._cfg["build_submit_argv"]
        result = self._run(render_argv(template, values), "submit")
        outcome = self._dialect.parse_submit(result)
        stamp = now_iso()
        handle = JobHandle(
            executor=self.name,
            driver=self.driver,
            native_job_id=outcome.job_id or "",
            task_id=task.task_id,
            leaf_id=task.leaf_id,
            attempt=task.attempt,
            cluster=outcome.cluster,
            submitted_at=stamp,
            executor_log=repo_rel(self._root, joblog),
        )
        if outcome.job_id is None:
            self._submit_failures += 1
            reason = f"submission failed: {outcome.error or result.failure_text}"
            failed = JobObservation(state=JobState.FAILED, reason=reason, observed_at=stamp)
            self._tracked[task.task_id] = _Tracked(
                task, handle, failed, script, joblog, settled=failed
            )
            self._event(f"{task.task_id}: {reason}")
            if self._submit_failures >= SUBMIT_FAILURE_LIMIT:
                raise ClusterError(
                    f"{self._submit_failures} consecutive submissions to `{self.name}` "
                    f"failed; last: {outcome.error or result.failure_text}"
                )
            return handle
        self._submit_failures = 0
        queued = JobObservation(
            state=JobState.QUEUED,
            reason=f"submitted to queue {outcome.queue}" if outcome.queue else "submitted",
            observed_at=stamp,
        )
        self._tracked[task.task_id] = _Tracked(task, handle, queued, script, joblog)
        return handle

    def submit_many(
        self,
        tasks: Sequence[LeafTask],
        on_submitted: Callable[[Sequence[JobHandle]], None] | None = None,
    ) -> list[JobHandle]:
        if not tasks:
            return []
        if not self.arrays_enabled or len(tasks) == 1:
            if self._arrays_off_reason and len(tasks) > 1 and self._array_sequence == 0:
                self._array_sequence += 1
                self._event(f"submitting plain jobs: {self._arrays_off_reason}")
            return super().submit_many(tasks, on_submitted)
        handles: list[JobHandle] = []
        for group in _homogeneous_groups(tasks):
            for start in range(0, len(group), self.array_chunk_size):
                chunk = group[start : start + self.array_chunk_size]
                submitted = (
                    [self.submit(chunk[0])] if len(chunk) == 1 else self._submit_array(chunk)
                )
                handles.extend(submitted)
                if on_submitted is not None:
                    on_submitted(submitted)
        by_task = {handle.task_id: handle for handle in handles}
        return [by_task[task.task_id] for task in tasks]

    def _submit_array(self, tasks: Sequence[LeafTask]) -> list[JobHandle]:
        for task in tasks:
            if task.manifest_path is None:
                raise ClusterError(f"{task.task_id}: no manifest was written for this attempt")
        self._array_sequence += 1
        label = f"{tasks[0].stage}-arr{self._array_sequence:04d}"
        script = self._write_array_script(tasks, label)
        tasks_file = array_tasks_path(self._run_dir, label)
        token = self._dialect.array_log_token
        joblog_pattern = logs_dir(self._run_dir) / f"{label}.{token}.log"
        joblog_pattern.parent.mkdir(parents=True, exist_ok=True)
        values = {
            **tasks[0].resources.placeholders(),
            "jobname": self._dialect.array_jobname(
                f"ocah.{self._run_dir.name}.{label}", len(tasks)
            ),
            "joblog": str(joblog_pattern),
            "script": str(script),
            "manifest": str(tasks_file),
            "python": sys.executable,
            "run_dir": str(self._run_dir),
            "repo_root": str(self._root),
            "leaf_dir": str(tasks_file.parent),
            "task_id": label,
            "executor": self.name,
            "array_range": f"1-{len(tasks)}",
        }
        result = self._run(render_argv(self._cfg["submit_argv"], values), "submit")
        outcome = self._dialect.parse_submit(result)
        stamp = now_iso()
        handles: list[JobHandle] = []
        if outcome.job_id is None:
            self._submit_failures += 1
            reason = f"array submission failed: {outcome.error or result.failure_text}"
            failed = JobObservation(state=JobState.FAILED, reason=reason, observed_at=stamp)
            for task in tasks:
                handle = JobHandle(
                    executor=self.name,
                    driver=self.driver,
                    native_job_id="",
                    task_id=task.task_id,
                    leaf_id=task.leaf_id,
                    attempt=task.attempt,
                    submitted_at=stamp,
                )
                self._tracked[task.task_id] = _Tracked(
                    task, handle, failed, script, joblog_pattern, array_label=label, settled=failed
                )
                handles.append(handle)
            self._event(f"{label} ({len(tasks)} attempts): {reason}")
            if self._submit_failures >= SUBMIT_FAILURE_LIMIT:
                raise ClusterError(
                    f"{self._submit_failures} consecutive submissions to `{self.name}` "
                    f"failed; last: {outcome.error or result.failure_text}"
                )
            return handles
        self._submit_failures = 0
        queued = JobObservation(
            state=JobState.QUEUED,
            reason=f"submitted to queue {outcome.queue}" if outcome.queue else "submitted",
            observed_at=stamp,
        )
        for index, task in enumerate(tasks, start=1):
            joblog = logs_dir(self._run_dir) / f"{label}.{index}.log"
            handle = JobHandle(
                executor=self.name,
                driver=self.driver,
                native_job_id=self._dialect.element_id(outcome.job_id, index),
                task_id=task.task_id,
                leaf_id=task.leaf_id,
                attempt=task.attempt,
                cluster=outcome.cluster,
                array_job_id=outcome.job_id,
                array_task_id=index,
                submitted_at=stamp,
                executor_log=repo_rel(self._root, joblog),
            )
            self._tracked[task.task_id] = _Tracked(
                task, handle, queued, script, joblog, array_label=label
            )
            handles.append(handle)
        self._event(
            f"{label}: {len(tasks)} attempts submitted as array {outcome.job_id} "
            f"({tasks[0].task_id} .. {tasks[-1].task_id})"
        )
        return handles

    def _write_array_script(self, tasks: Sequence[LeafTask], label: str) -> Path:
        tasks_file = array_tasks_path(self._run_dir, label)
        tasks_file.parent.mkdir(parents=True, exist_ok=True)
        tasks_file.write_text(
            "".join(f"{task.task_id}\t{task.manifest_path}\t{task.leaf_dir}\n" for task in tasks),
            encoding="utf-8",
        )
        values = {
            "python": sys.executable,
            "repo_root": str(self._root),
            "run_dir": str(self._run_dir),
            **{name: sentinel for name, (sentinel, _var) in _ARRAY_TOKENS.items()},
        }
        worker = render_argv(self._cfg.get("worker_argv") or DEFAULT_WORKER_ARGV, values)
        exec_line = " ".join(shlex.quote(part) for part in worker)
        for sentinel, variable in _ARRAY_TOKENS.values():
            exec_line = exec_line.replace(sentinel, f'"${variable}"')
        index_env = self._dialect.array_index_env
        lines = [
            "#!/bin/sh",
            f"# run_dv.py leaf attempts {label}: element ${index_env} of {len(tasks)}",
        ]
        for name in self._passthrough:
            if name in self._env:
                lines.append(f"export {name}={shlex.quote(self._env[name])}")
        lines += [
            f"cd {shlex.quote(str(self._root))} || exit 2",
            f'OCAH_TASK_LINE=$(sed -n "${{{index_env}}}p" {shlex.quote(str(tasks_file))}) || exit 2',
            '[ -n "$OCAH_TASK_LINE" ] || exit 2',
            "OCAH_TASK_ID=$(printf '%s\\n' \"$OCAH_TASK_LINE\" | cut -f1)",
            "OCAH_MANIFEST=$(printf '%s\\n' \"$OCAH_TASK_LINE\" | cut -f2)",
            "OCAH_LEAF_DIR=$(printf '%s\\n' \"$OCAH_TASK_LINE\" | cut -f3)",
            "export OCAH_TASK_ID OCAH_MANIFEST OCAH_LEAF_DIR",
            "exec " + exec_line,
        ]
        path = script_path(self._run_dir, label)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def _job_name(self, task: LeafTask) -> str:
        return f"ocah.{self._run_dir.name}.{task.task_id}"

    def _write_script(self, task: LeafTask) -> Path:
        path = script_path(self._run_dir, task.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        values = {
            "python": sys.executable,
            "manifest": str(task.manifest_path),
            "repo_root": str(self._root),
            "run_dir": str(self._run_dir),
            "leaf_dir": str(task.leaf_dir),
            "task_id": task.task_id,
        }
        worker = render_argv(self._cfg.get("worker_argv") or DEFAULT_WORKER_ARGV, values)
        lines = ["#!/bin/sh", f"# run_dv.py leaf attempt {task.task_id}"]
        for name in self._passthrough:
            if name in self._env:
                lines.append(f"export {name}={shlex.quote(self._env[name])}")
        lines.append(f"cd {shlex.quote(str(self._root))} || exit 2")
        lines.append("exec " + " ".join(shlex.quote(part) for part in worker))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    # -- poll ------------------------------------------------------------------------------

    def poll(self, handles: Sequence[JobHandle]) -> dict[str, JobObservation]:
        now = self._clock()
        stamp = now_iso()
        out: dict[str, JobObservation] = {}
        live: list[_Tracked] = []
        for handle in handles:
            tracked = self._tracked.get(handle.task_id)
            if tracked is None:
                out[handle.task_id] = JobObservation(
                    state=JobState.LOST, reason="not submitted by this executor", observed_at=stamp
                )
            elif tracked.settled is not None:
                out[handle.task_id] = tracked.settled
            else:
                live.append(tracked)
        if not live:
            return out
        answer = self._query(live, self._cfg["query_argv"], self._dialect.parse_query)
        reconciling: list[_Tracked] = []
        for tracked in live:
            task_id = tracked.task.task_id
            job_id = tracked.handle.native_job_id
            if job_id in answer.failed:
                out[task_id] = tracked.last
                continue
            seen = answer.observations.get(job_id)
            if seen is None or seen.state is JobState.RECONCILING:
                reconciling.append(tracked)
                continue
            out[task_id] = self._settle(tracked, seen, now)
        if reconciling:
            self._consult_history(reconciling)
            for tracked in reconciling:
                out[tracked.task.task_id] = self._reconcile(tracked, now, stamp)
        if answer.failed:
            self._query_failures += 1
            self._event(
                f"query failed ({self._query_failures}/{QUERY_FAILURE_LIMIT}): {answer.error}"
            )
            if self._query_failures >= QUERY_FAILURE_LIMIT:
                raise ClusterError(
                    f"{self._query_failures} consecutive `{self.name}` queries failed; "
                    f"last: {answer.error}"
                )
        else:
            self._query_failures = 0
        return out

    def _query(
        self,
        tracked: Sequence[_Tracked],
        template: Sequence[Any],
        parse: Callable[[CommandResult, Sequence[str]], QueryOutcome],
        *,
        purpose: str = "query",
    ) -> QueryOutcome:
        """Run one template over every tracked job, batched or per id as the template asks."""
        ids = [entry.handle.native_job_id for entry in tracked]
        answer = QueryOutcome()
        per_id = self._per_id_template(template)
        for start in range(0, len(ids), self.query_batch_size):
            batch = ids[start : start + self.query_batch_size]
            if per_id:
                for job_id in batch:
                    answer.merge(self._query_ids(template, [job_id], parse, purpose))
                continue
            outcome = self._query_ids(template, batch, parse, purpose)
            if outcome.failed and len(batch) > 1 and self._dialect.retry_failed_query_per_id:
                outcome = QueryOutcome()
                for job_id in batch:
                    outcome.merge(self._query_ids(template, [job_id], parse, purpose))
            answer.merge(outcome)
        return answer

    def _query_ids(
        self,
        template: Sequence[Any],
        job_ids: Sequence[str],
        parse: Callable[[CommandResult, Sequence[str]], QueryOutcome],
        purpose: str,
    ) -> QueryOutcome:
        argv = render_argv(
            template,
            {"job_id": job_ids[0], "job_ids_csv": ",".join(job_ids)},
            {"job_ids_argv": list(job_ids)},
        )
        result = self._run(argv, purpose)
        try:
            return parse(result, job_ids)
        except (ValueError, KeyError, TypeError) as exc:
            failed = whole_command_failed(result, job_ids)
            failed.error = f"unparsable {purpose} output: {exc}"
            return failed

    @staticmethod
    def _per_id_template(template: Sequence[Any]) -> bool:
        def names(elements: Sequence[Any]) -> set[str]:
            found: set[str] = set()
            for element in elements:
                if isinstance(element, list):
                    found |= names(element)
                else:
                    found |= set(PLACEHOLDER_RE.findall(str(element)))
            return found

        return "job_id" in names(template)

    def _settle(self, tracked: _Tracked, seen: JobObservation, now: float) -> JobObservation:
        """Apply one live observation; a terminal one waits for the leaf's result within grace."""
        if not seen.state.terminal:
            tracked.missing_since = None
            tracked.terminal_since = None
            tracked.last = seen
            return seen
        if tracked.terminal_since is None:
            tracked.terminal_since = now
        if seen.state not in _RESULT_BEARING or self._artifacts_visible(tracked):
            if seen.exit_code is None and seen.state in _RESULT_BEARING:
                recorded = self._completion_observation(tracked, seen.observed_at)
                if recorded is not None and recorded.exit_code is not None:
                    seen = JobObservation(
                        state=seen.state,
                        exit_code=recorded.exit_code,
                        reason=seen.reason,
                        observed_at=seen.observed_at,
                        raw=seen.raw,
                    )
            return self._finish(tracked, seen)
        if now - tracked.terminal_since >= self.artifact_grace_sec:
            code = "" if seen.exit_code is None else f" with exit code {seen.exit_code}"
            reason = (
                f"{seen.state.value.lower()} reported{code} but no result.json appeared within "
                f"{self.artifact_grace_sec:g}s"
            )
            return self._finish(
                tracked,
                JobObservation(
                    state=seen.state,
                    exit_code=seen.exit_code,
                    reason=f"{reason}; {seen.reason}" if seen.reason else reason,
                    observed_at=seen.observed_at,
                    raw=seen.raw,
                ),
            )
        waiting = JobObservation(
            state=JobState.RECONCILING,
            exit_code=seen.exit_code,
            reason=f"{seen.state.value.lower()} reported; waiting for result.json",
            observed_at=seen.observed_at,
            raw=seen.raw,
        )
        tracked.last = waiting
        return waiting

    def _consult_history(self, reconciling: Sequence[_Tracked]) -> None:
        """Ask the scheduler's history once per poll for every vanished job it has not settled."""
        if not self._history_template:
            return
        pending = [
            tracked
            for tracked in reconciling
            if tracked.history is None and not self._artifacts_visible(tracked)
        ]
        if not pending:
            return

        def parse(result: CommandResult, job_ids: Sequence[str]) -> QueryOutcome:
            return self._dialect.parse_history(result, job_ids, self._history_parser)

        answer = self._query(pending, self._history_template, parse, purpose="history")
        for tracked in pending:
            seen = answer.observations.get(tracked.handle.native_job_id)
            if seen is not None and seen.state.terminal:
                tracked.history = seen

    def _reconcile(self, tracked: _Tracked, now: float, stamp: str) -> JobObservation:
        """Settle a job the live query does not know: artifacts, then history, then the grace."""
        if tracked.missing_since is None:
            tracked.missing_since = now
        completed = self._completion_observation(tracked, stamp)
        if completed is not None:
            return self._finish(tracked, completed)
        if tracked.history is not None:
            return self._settle(tracked, tracked.history, now)
        if now - tracked.missing_since >= self.artifact_grace_sec:
            return self._finish(
                tracked,
                JobObservation(
                    state=JobState.LOST,
                    reason=(
                        f"missing from the live query for {self.artifact_grace_sec:g}s with "
                        "no history record and no result"
                    ),
                    observed_at=stamp,
                ),
            )
        waiting = JobObservation(
            state=JobState.RECONCILING, reason="missing from the live query", observed_at=stamp
        )
        tracked.last = waiting
        return waiting

    def _completion_observation(self, tracked: _Tracked, stamp: str) -> JobObservation | None:
        path = completion_path(self._run_dir, tracked.task.task_id)
        if not path.is_file():
            if tracked.task.result_json.is_file():
                return JobObservation(
                    state=JobState.SUCCEEDED,
                    reason="reconciled from the leaf's result.json",
                    observed_at=stamp,
                )
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        code = record.get("return_code") if isinstance(record, dict) else None
        exit_code = int(code) if isinstance(code, int) else None
        return JobObservation(
            state=JobState.SUCCEEDED if exit_code in (0, None) else JobState.FAILED,
            exit_code=exit_code,
            reason="reconciled from the worker's completion record",
            observed_at=stamp,
        )

    def _artifacts_visible(self, tracked: _Tracked) -> bool:
        return (
            tracked.task.result_json.is_file()
            or completion_path(self._run_dir, tracked.task.task_id).is_file()
        )

    def _finish(self, tracked: _Tracked, seen: JobObservation) -> JobObservation:
        tracked.settled = seen
        tracked.last = seen
        self._event(
            f"{tracked.task.task_id} job {tracked.handle.native_job_id}: "
            f"{seen.state.value.lower()}" + (f" ({seen.reason})" if seen.reason else "")
        )
        return seen

    # -- wait ------------------------------------------------------------------------------

    def wait(self, handles: Sequence[JobHandle], timeout_sec: float) -> None:
        if timeout_sec <= 0 or not handles:
            return
        for handle in handles:
            tracked = self._tracked.get(handle.task_id)
            if tracked is not None and tracked.settled is not None:
                return
        self._sleep(timeout_sec * min(2**self._query_failures, 8))

    # -- cancel ----------------------------------------------------------------------------

    def cancel(
        self,
        handles: Sequence[JobHandle],
        *,
        grace_sec: float,
        stop: threading.Event | None = None,
    ) -> dict[str, bool]:
        """Cancel the run's own jobs and confirm each by query within the grace.

        A job the scheduler reports finished counts as confirmed; one it does not know, or
        one live when the grace ends or ``stop`` is set, stays unconfirmed and is recorded
        beside the manifests for the operator. Nothing here raises: an interrupted
        run must reach its summary whatever the scheduler does.
        """
        confirmed: dict[str, bool] = {}
        targets: list[_Tracked] = []
        for handle in handles:
            tracked = self._tracked.get(handle.task_id)
            if tracked is None or tracked.settled is not None or not handle.native_job_id:
                confirmed[handle.task_id] = True
                continue
            targets.append(tracked)
        if not targets:
            return confirmed
        replies: dict[str, CancelReply] = {}
        template = self._cfg["cancel_argv"]
        ids = [tracked.handle.native_job_id for tracked in targets]
        step = 1 if self._per_id_template(template) else self.query_batch_size
        for start in range(0, len(ids), step):
            batch = ids[start : start + step]
            argv = render_argv(
                template,
                {"job_id": batch[0], "job_ids_csv": ",".join(batch)},
                {"job_ids_argv": batch},
            )
            result = self._run(argv, "cancel")
            try:
                replies.update(self._dialect.parse_cancel(result, batch))
            except (ValueError, KeyError, TypeError) as exc:
                self._event(f"unparsable cancel output: {exc}")
                replies.update({job_id: CancelReply.UNKNOWN for job_id in batch})
        outstanding: list[_Tracked] = []
        for tracked in targets:
            reply = replies.get(tracked.handle.native_job_id, CancelReply.UNKNOWN)
            if reply is CancelReply.FINISHED:
                confirmed[tracked.task.task_id] = True
            elif reply is CancelReply.REQUESTED:
                outstanding.append(tracked)
            else:
                confirmed[tracked.task.task_id] = False
        deadline = self._clock() + max(0.0, grace_sec)
        while outstanding:
            answer = self._query(outstanding, self._cfg["query_argv"], self._dialect.parse_query)
            for tracked in list(outstanding):
                job_id = tracked.handle.native_job_id
                seen = answer.observations.get(job_id)
                if job_id in answer.missing:
                    seen = JobObservation(
                        state=JobState.CANCELLED,
                        reason="absent from the live query after the cancel request",
                        observed_at=now_iso(),
                    )
                if seen is not None and seen.state.terminal:
                    self._finish(tracked, seen)
                    confirmed[tracked.task.task_id] = True
                    outstanding.remove(tracked)
            remaining = deadline - self._clock()
            if not outstanding or remaining <= 0 or (stop is not None and stop.is_set()):
                break
            self._sleep(min(CANCEL_POLL_SEC, remaining))
        for tracked in outstanding:
            confirmed[tracked.task.task_id] = False
        unconfirmed = [tracked for tracked in targets if not confirmed[tracked.task.task_id]]
        if unconfirmed:
            self._record_unconfirmed(unconfirmed, replies)
        return confirmed

    def _record_unconfirmed(
        self, unconfirmed: Sequence[_Tracked], replies: Mapping[str, CancelReply]
    ) -> None:
        records = [
            {
                **tracked.handle.to_dict(),
                "cancel_reply": replies.get(
                    tracked.handle.native_job_id, CancelReply.UNKNOWN
                ).value,
                "last_state": tracked.last.state.value,
                "recorded_at": now_iso(),
            }
            for tracked in unconfirmed
        ]
        try:
            write_result(self.unconfirmed_cancels, {"executor": self.name, "jobs": records})
        except OSError as exc:
            self._event(f"cannot record unconfirmed cancellations: {exc}")
        ids = ", ".join(tracked.handle.native_job_id for tracked in unconfirmed)
        self._event(
            f"{len(unconfirmed)} cancellation(s) unconfirmed (job ids {ids}); "
            f"recorded in {repo_rel(self._root, self.unconfirmed_cancels)}"
        )

    # -- collect ---------------------------------------------------------------------------

    def collect(self, handle: JobHandle) -> ExecutionResult:
        tracked = self._tracked.pop(handle.task_id, None)
        if tracked is None:
            return ExecutionResult(
                task_id=handle.task_id,
                state=JobState.LOST,
                error="not submitted by this executor",
            )
        seen = tracked.settled or tracked.last
        task = tracked.task
        scheduler = {"job_id": handle.native_job_id, "state": seen.state.value}
        joblog = repo_rel(self._root, tracked.joblog) if tracked.joblog.is_file() else None
        result = self._read_result(task)
        if result is not None:
            result.metadata = {**(result.metadata or {}), "scheduler": scheduler}
            if joblog:
                result.artifacts = {**(result.artifacts or {}), "executor_log": joblog}
            return ExecutionResult(
                task_id=handle.task_id,
                state=seen.state,
                result=result,
                result_json=repo_rel(self._root, task.result_json),
            )
        if seen.state is JobState.TIMED_OUT:
            ended = seen.observed_at or now_iso()
            expired = f"scheduler wall time expired: {seen.reason or 'no detail'}"
            result = StageResult(
                stage=task.stage,
                item=task.item,
                status="TIMEOUT",
                return_code=124,
                duration_sec=0.0,
                started_at=handle.submitted_at or ended,
                ended_at=ended,
                log=joblog,
                artifacts={"executor_log": joblog} if joblog else {},
                failure_buckets=[{"kind": "timeout", "signature": expired[:120], "count": 1}],
                reason=expired,
                metadata={
                    "seed": task.seed,
                    "attempt": task.attempt,
                    "debug_only": task.debug_only,
                    "scheduler": scheduler,
                },
                target=task.target,
            )
            return ExecutionResult(task_id=handle.task_id, state=seen.state, result=result)
        return ExecutionResult(
            task_id=handle.task_id,
            state=seen.state,
            error=seen.reason or seen.state.value.lower(),
        )

    def _read_result(self, task: LeafTask) -> StageResult | None:
        path = task.result_json
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._event(f"{task.task_id}: unreadable {path}: {exc}")
            return None
        if not isinstance(payload, dict):
            return None
        return result_from_fragment(payload, stage=task.stage, item=task.item)

    # -- commands and logging ----------------------------------------------------------------

    def _run(self, argv: list[str], purpose: str) -> CommandResult:
        started = self._clock()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self._root),
                env=self._env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.command_timeout_sec,
                check=False,
            )
            result = CommandResult(
                argv, proc.returncode, proc.stdout, proc.stderr, self._clock() - started
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                argv,
                None,
                _text(exc.stdout),
                _text(exc.stderr),
                self._clock() - started,
                timed_out=True,
            )
        except OSError as exc:
            result = CommandResult(argv, None, "", str(exc), self._clock() - started)
        self._log(purpose, result)
        return result

    def _log(self, purpose: str, result: CommandResult) -> None:
        try:
            if self._log_handle is None:
                self.executor_log.parent.mkdir(parents=True, exist_ok=True)
                self._log_handle = self.executor_log.open("a", encoding="utf-8")
            status = "timeout" if result.timed_out else f"rc={result.returncode}"
            self._log_handle.write(
                f"{now_iso()} {purpose} {status} {result.duration_sec:.2f}s "
                + " ".join(shlex.quote(part) for part in result.argv)
                + "\n"
            )
            for stream, text in (("stdout", result.stdout), ("stderr", result.stderr)):
                if text.strip():
                    body = text[:OUTPUT_LOG_LIMIT]
                    if len(text) > OUTPUT_LOG_LIMIT:
                        body += f"... [{len(text) - OUTPUT_LOG_LIMIT} more characters]"
                    for line in body.rstrip("\n").splitlines():
                        self._log_handle.write(f"    {stream}: {line}\n")
            self._log_handle.flush()
        except OSError:
            self._log_handle = None

    def _event(self, message: str) -> None:
        try:
            if self._log_handle is None:
                self.executor_log.parent.mkdir(parents=True, exist_ok=True)
                self._log_handle = self.executor_log.open("a", encoding="utf-8")
            self._log_handle.write(f"{now_iso()} note {message}\n")
            self._log_handle.flush()
        except OSError:
            self._log_handle = None
        if self._on_event is not None:
            self._on_event(message)

    def close(self, *, wait: bool = True) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None


def _template_placeholders(template: Sequence[Any]) -> set[str]:
    found: set[str] = set()
    for element in template:
        if isinstance(element, list):
            found |= _template_placeholders(element)
        else:
            found |= set(PLACEHOLDER_RE.findall(str(element)))
    return found


def _homogeneous_groups(tasks: Sequence[LeafTask]) -> list[list[LeafTask]]:
    """Consecutive tasks that share a stage and a resource request, in submission order."""
    groups: list[list[LeafTask]] = []
    for task in tasks:
        if groups and (
            groups[-1][0].stage == task.stage and groups[-1][0].resources == task.resources
        ):
            groups[-1].append(task)
        else:
            groups.append([task])
    return groups


def _text(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


__all__ = [
    "ARRAY_TASKS_SUFFIX",
    "CANCEL_POLL_SEC",
    "DEFAULT_WORKER_ARGV",
    "EXECUTOR_LOG_NAME",
    "OUTPUT_LOG_LIMIT",
    "QUERY_FAILURE_LIMIT",
    "SUBMIT_FAILURE_LIMIT",
    "UNCONFIRMED_CANCELS_NAME",
    "CancelReply",
    "ClusterError",
    "ClusterExecutor",
    "CommandResult",
    "QueryOutcome",
    "SchedulerDialect",
    "SubmitOutcome",
    "array_tasks_path",
    "base_job_id",
    "job_log_path",
    "logs_dir",
    "script_path",
    "scripts_dir",
    "whole_command_failed",
]
