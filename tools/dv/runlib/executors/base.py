# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The executor contract: how one leaf attempt reaches a machine and how its outcome returns.

An executor takes a :class:`LeafTask`, answers with a :class:`JobHandle`, reports a normalized
:class:`JobState` per handle from ``poll``, confirms ``cancel``, and hands the attempt's
:class:`~runlib.models.StageResult` back through ``collect``. The local executor runs the
attempt inside this process; a cluster driver submits the worker entry point to a scheduler
and reads the leaf's ``result.json`` back. The coordinator loop in ``runlib.cli`` is the same
for every executor, so scheduler state never decides a DV verdict: a leaf's own result does.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..compat import UTC
from ..config import parse_walltime_sec
from ..models import ConfigError, StageResult

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
# Argv templates hold strings and optional groups, which are nested string lists.
ArgvTemplate = list[Any]


class JobState(str, Enum):
    """The scheduler-side lifecycle every driver maps its native states onto."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    # Missing from the live query; history and artifacts decide within a bounded grace.
    RECONCILING = "RECONCILING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"
    LOST = "LOST"

    @property
    def terminal(self) -> bool:
        return self in TERMINAL_STATES


TERMINAL_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.TIMED_OUT,
        JobState.CANCELLED,
        JobState.PREEMPTED,
        JobState.LOST,
    }
)


@dataclass(frozen=True)
class ResourceRequest:
    """The normalized resource vocabulary a driver translates into scheduler flags.

    ``walltime`` keeps the text the request was written in; :meth:`placeholders` renders the
    unit-specific forms (minutes, ``HH:MM:SS``, seconds) so a site template picks the one its
    scheduler wants. ``mem_mb`` renders both as megabytes and as whole gigabytes for the same
    reason.
    """

    queue: str | None = None
    cores: int | None = None
    mem_mb: int | None = None
    walltime: str | None = None

    def placeholders(self) -> dict[str, str]:
        values: dict[str, str] = {}
        if self.queue:
            values["queue"] = self.queue
        if self.cores is not None:
            values["cores"] = str(self.cores)
        if self.mem_mb is not None:
            values["mem_mb"] = str(self.mem_mb)
            values["mem_gb"] = str(max(1, -(-self.mem_mb // 1024)))
        if self.walltime:
            seconds = parse_walltime_sec(self.walltime)
            values["walltime"] = self.walltime
            values["walltime_sec"] = str(seconds)
            values["walltime_min"] = str(-(-seconds // 60))
            values["walltime_hms"] = (
                f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
            )
        return values

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ResourceRequest:
        data = data or {}
        cores = data.get("cores")
        mem_mb = data.get("mem_mb")
        return cls(
            queue=str(data["queue"]) if data.get("queue") else None,
            cores=int(cores) if cores is not None else None,
            mem_mb=int(mem_mb) if mem_mb is not None else None,
            walltime=str(data["walltime"]) if data.get("walltime") else None,
        )


def resolve_resources(*layers: ResourceRequest) -> ResourceRequest:
    """Field by field, the first layer that sets a value wins."""
    merged: dict[str, Any] = {}
    for name in ("queue", "cores", "mem_mb", "walltime"):
        for layer in layers:
            value = getattr(layer, name)
            if value is not None:
                merged[name] = value
                break
    return ResourceRequest(**merged)


def render_argv(
    template: Sequence[Any],
    values: Mapping[str, str],
    lists: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Render an executor argv template.

    A string element renders every ``{name}`` from ``values``. An element that is exactly one
    placeholder named in ``lists`` splices that list's tokens. A nested list is an optional
    group: it renders whole when every placeholder in it has a value and is dropped otherwise,
    so a template can carry ``["-q", "{queue}"]`` without forcing every run to name a queue.
    """
    lists = lists or {}
    out: list[str] = []
    for element in template:
        if isinstance(element, list):
            names = {name for text in element for name in PLACEHOLDER_RE.findall(str(text))}
            if all(name in values or name in lists for name in names):
                out.extend(render_argv(element, values, lists))
            continue
        text = str(element)
        match = PLACEHOLDER_RE.fullmatch(text)
        if match and match.group(1) in lists:
            out.extend(str(token) for token in lists[match.group(1)])
            continue

        def substitute(found: re.Match[str]) -> str:
            name = found.group(1)
            if name not in values:
                raise ConfigError(f"argv template needs a value for {{{name}}}: {text!r}")
            return values[name]

        out.append(PLACEHOLDER_RE.sub(substitute, text))
    return out


def task_identifier(stage: str, leaf_id: int, attempt: int, *, debug_only: bool = False) -> str:
    """The stable name of one attempt: ``sim-000012-a1``, ``-debug`` on a wave-debug rerun."""
    return f"{stage}-{leaf_id:06d}-a{attempt}" + ("-debug" if debug_only else "")


@dataclass(frozen=True)
class LeafTask:
    """One attempt of one leaf: the unit an executor runs."""

    task_id: str
    leaf_id: int
    stage: str
    item: str
    seed: int
    attempt: int
    run_dir: Path
    leaf_dir: Path
    target: str | None = None
    nest: bool = False
    # A wave-debug rerun of a failed final attempt; its status never grades the leaf.
    debug_only: bool = False
    timeout_sec: int | None = None
    resources: ResourceRequest = field(default_factory=ResourceRequest)
    # Public command-line attributes this attempt changes against the run's command line, such
    # as the wave settings of a debug rerun.
    args_overrides: dict[str, Any] = field(default_factory=dict)
    # The failure time parsed from the graded attempt's log, which a debug rerun windows its
    # dump around.
    wave_failure_time: Any = None
    manifest_path: Path | None = None

    @property
    def result_json(self) -> Path:
        return self.leaf_dir / "result.json"


@dataclass
class JobHandle:
    """The ticket the coordinator keeps for one submitted attempt."""

    executor: str
    driver: str
    native_job_id: str
    task_id: str
    leaf_id: int
    attempt: int
    # Slurm's optional ``jobid;cluster`` suffix.
    cluster: str | None = None
    array_job_id: str | None = None
    array_task_id: int | None = None
    submission_token: str = ""
    submitted_at: str = ""
    executor_log: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobObservation:
    """What one poll saw for one handle."""

    state: JobState
    exit_code: int | None = None
    reason: str = ""
    observed_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """What ``collect`` recovers for a terminal handle."""

    task_id: str
    state: JobState
    result: StageResult | None = None
    result_json: str | None = None
    error: str = ""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def error_result(task: LeafTask, reason: str, *, started_at: str | None = None) -> StageResult:
    """The ``ERROR`` a leaf grades to when its attempt produced no result of its own."""
    stamp = now_iso()
    return StageResult(
        stage=task.stage,
        item=task.item,
        status="ERROR",
        return_code=1,
        duration_sec=0.0,
        started_at=started_at or stamp,
        ended_at=stamp,
        reason=reason,
        metadata={"seed": task.seed, "attempt": task.attempt, "debug_only": task.debug_only},
        target=task.target,
    )


def result_from_fragment(payload: Mapping[str, Any], *, stage: str, item: str) -> StageResult:
    """A leaf ``result.json`` read back as the :class:`StageResult` that wrote it."""
    metadata = payload.get("metadata")
    return StageResult(
        stage=stage,
        item=str(payload.get("item", item)),
        status=str(payload.get("status", "UNKNOWN")),
        return_code=int(payload.get("return_code", 1)),
        duration_sec=float(payload.get("duration_sec", 0.0)),
        started_at=str(payload.get("started_at", "")),
        ended_at=str(payload.get("ended_at", "")),
        log=payload.get("log"),
        artifacts=dict(payload.get("artifacts") or {}),
        failure_buckets=list(payload.get("failure_buckets") or []),
        reason=str(payload.get("reason", "")),
        parser=payload.get("parser"),
        metadata=dict(metadata) if isinstance(metadata, dict) else None,
        target=payload.get("target"),
        formal=payload.get("formal"),
    )


class Executor(ABC):
    """Submit, poll, cancel, collect: the four verbs every driver implements."""

    name: str
    driver: str
    # A driver that runs attempts in another process reads the leaf manifest; the local
    # executor runs them in this one.
    requires_manifest: bool = False
    # Submissions the coordinator makes between two polls; None leaves it unbounded.
    submit_batch_size: int | None = None

    @property
    @abstractmethod
    def max_in_flight(self) -> int:
        """Attempts the coordinator keeps queued or running at once."""

    @abstractmethod
    def submit(self, task: LeafTask) -> JobHandle: ...

    @abstractmethod
    def poll(self, handles: Sequence[JobHandle]) -> dict[str, JobObservation]:
        """Observations keyed by ``task_id`` for every handle asked about."""

    def wait(self, handles: Sequence[JobHandle], timeout_sec: float) -> None:
        """Block until a handle may have changed state, or ``timeout_sec`` passes."""
        if handles and timeout_sec > 0:
            time.sleep(timeout_sec)

    @abstractmethod
    def cancel(self, handles: Sequence[JobHandle], *, grace_sec: float) -> dict[str, bool]:
        """Ask the backend to stop every handle; True per ``task_id`` once the stop is confirmed."""

    @abstractmethod
    def collect(self, handle: JobHandle) -> ExecutionResult:
        """The attempt's result for a terminal handle."""

    def close(self, *, wait: bool = True) -> None:
        """Release the backend; with ``wait`` False, abandon queued attempts."""


__all__ = [
    "ArgvTemplate",
    "ExecutionResult",
    "Executor",
    "JobHandle",
    "JobObservation",
    "JobState",
    "LeafTask",
    "PLACEHOLDER_RE",
    "ResourceRequest",
    "TERMINAL_STATES",
    "error_result",
    "now_iso",
    "render_argv",
    "resolve_resources",
    "result_from_fragment",
    "task_identifier",
]
