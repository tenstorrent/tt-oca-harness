# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The local executor: leaf attempts run inside this process.

With one worker the attempt runs inline on the calling thread, so a single test or a
sequential regression keeps the process's signal handling and console exactly as a direct
call would. With more workers the attempts run on a thread pool bounded by the same count.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from ..models import StageResult
from ..stages import request_stage_cancellation
from .base import (
    ExecutionResult,
    Executor,
    JobHandle,
    JobObservation,
    JobState,
    LeafTask,
    now_iso,
)

AttemptRunner = Callable[[LeafTask], StageResult]


class LocalExecutor(Executor):
    driver = "local"
    requires_manifest = False

    def __init__(self, name: str, runner: AttemptRunner, *, max_workers: int) -> None:
        self.name = name
        self._runner = runner
        self._max_workers = max(1, int(max_workers))
        self._pool: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=self._max_workers) if self._max_workers > 1 else None
        )
        self._futures: dict[str, Future[StageResult]] = {}
        self._inline: dict[str, tuple[StageResult | None, BaseException | None]] = {}
        self._sequence = 0

    @property
    def max_in_flight(self) -> int:
        return self._max_workers

    def submit(self, task: LeafTask) -> JobHandle:
        self._sequence += 1
        handle = JobHandle(
            executor=self.name,
            driver=self.driver,
            native_job_id=f"local-{self._sequence}",
            task_id=task.task_id,
            leaf_id=task.leaf_id,
            attempt=task.attempt,
            submitted_at=now_iso(),
        )
        if self._pool is None:
            # Inline: a BaseException such as the run's own interruption propagates to the
            # caller unchanged, as a direct call would let it.
            try:
                self._inline[task.task_id] = (self._runner(task), None)
            except Exception as exc:  # noqa: BLE001
                self._inline[task.task_id] = (None, exc)
            return handle
        self._futures[task.task_id] = self._pool.submit(self._runner, task)
        return handle

    def poll(self, handles: Sequence[JobHandle]) -> dict[str, JobObservation]:
        stamp = now_iso()
        out: dict[str, JobObservation] = {}
        for handle in handles:
            task_id = handle.task_id
            if task_id in self._inline:
                _, exc = self._inline[task_id]
                state = JobState.FAILED if exc is not None else JobState.SUCCEEDED
                out[task_id] = JobObservation(state=state, reason=str(exc or ""), observed_at=stamp)
                continue
            future = self._futures.get(task_id)
            if future is None:
                out[task_id] = JobObservation(state=JobState.LOST, observed_at=stamp)
            elif future.cancelled():
                out[task_id] = JobObservation(state=JobState.CANCELLED, observed_at=stamp)
            elif future.done():
                exc = future.exception()
                state = JobState.FAILED if exc is not None else JobState.SUCCEEDED
                out[task_id] = JobObservation(state=state, reason=str(exc or ""), observed_at=stamp)
            elif future.running():
                out[task_id] = JobObservation(state=JobState.RUNNING, observed_at=stamp)
            else:
                out[task_id] = JobObservation(state=JobState.QUEUED, observed_at=stamp)
        return out

    def wait(self, handles: Sequence[JobHandle], timeout_sec: float) -> None:
        futures = [
            self._futures[handle.task_id] for handle in handles if handle.task_id in self._futures
        ]
        if futures:
            wait(futures, timeout=timeout_sec, return_when=FIRST_COMPLETED)

    def cancel(self, handles: Sequence[JobHandle], *, grace_sec: float) -> dict[str, bool]:
        futures = {
            handle.task_id: self._futures[handle.task_id]
            for handle in handles
            if handle.task_id in self._futures
        }
        running = False
        for future in futures.values():
            if not future.cancel() and not future.done():
                running = True
        if running:
            request_stage_cancellation()
            wait(list(futures.values()), timeout=grace_sec)
        confirmed = {task_id: future.done() for task_id, future in futures.items()}
        for handle in handles:
            confirmed.setdefault(handle.task_id, True)
        return confirmed

    def collect(self, handle: JobHandle) -> ExecutionResult:
        task_id = handle.task_id
        if task_id in self._inline:
            result, exc = self._inline.pop(task_id)
            if exc is not None:
                return ExecutionResult(task_id=task_id, state=JobState.FAILED, error=str(exc))
            return ExecutionResult(task_id=task_id, state=JobState.SUCCEEDED, result=result)
        future = self._futures.pop(task_id, None)
        if future is None:
            return ExecutionResult(task_id=task_id, state=JobState.LOST, error="no such attempt")
        if future.cancelled():
            return ExecutionResult(task_id=task_id, state=JobState.CANCELLED, error="cancelled")
        exc = future.exception()
        if exc is not None:
            return ExecutionResult(task_id=task_id, state=JobState.FAILED, error=str(exc))
        return ExecutionResult(task_id=task_id, state=JobState.SUCCEEDED, result=future.result())

    def close(self, *, wait: bool = True) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=not wait)


__all__ = ["AttemptRunner", "LocalExecutor"]
