# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run-epoch record of one background monitor task.

A monitor (fabric tap, bit watch, SPI pad sampler) samples in one cocotb task
from ``start`` to ``stop``. Each ``start`` opens a new run epoch; each ``stop``
closes it and records the clock of its last sample. A mark carries the epoch in
which it was taken.

``check`` raises ``MonitorLifeError`` before a query reads the record when:

* the task ended without ``stop``: it raised, returned, or was cancelled from
  elsewhere. The error chains the exception of the task;
* the mark was taken while no run was open, or in an earlier epoch, so the
  record has a gap between the mark and the query.

A query that passes ``check`` therefore reads a record that is continuous from
the mark to the query, or to the ``stop`` that closed the run. ``stop`` raises
the same error when the task ended before it.
"""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import cocotb

# Epoch of a mark taken while no run was open.
NO_RUN = -1


class MonitorLifeError(AssertionError):
    """A monitor task ended before a graded window closed, or a mark spans a gap."""


@dataclass
class MonitorRun:
    """One run of the monitor task: its epoch, first and last sampled clocks, and end."""

    epoch: int
    start_clk: int
    end_clk: int | None = None
    end: str = "running"
    """``running``, ``stopped`` (by ``stop``), or ``died`` (any other end)."""


class MonitorLife:
    """Starts, stops and checks the task of one monitor."""

    def __init__(self, name: str, clk: Callable[[], int]) -> None:
        self.name = name
        self._clk = clk
        self.epoch = 0
        self.runs: list[MonitorRun] = []
        self._task: Any = None
        self._stopping = False
        self._fault: BaseException | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and self._fault is None

    def mark_epoch(self) -> int:
        """The epoch to store in a mark: the open run, or ``NO_RUN``."""
        return self.epoch if self._task is not None else NO_RUN

    def start(self, coro: Coroutine[Any, Any, None]) -> Any:
        """Open a new run epoch and start ``coro`` in it; returns the task."""
        self.epoch += 1
        self._stopping = False
        self._fault = None
        self.runs.append(MonitorRun(self.epoch, self._clk()))
        self._task = cocotb.start_soon(self._guard(coro, self.runs[-1]))
        return self._task

    async def _guard(self, coro: Coroutine[Any, Any, None], run: MonitorRun) -> None:
        try:
            await coro
        except CancelledError:
            if not self._stopping:
                self._died(run, MonitorLifeError(f"{self.name}: task cancelled outside stop()"))
            raise
        except BaseException as exc:
            self._died(run, exc)
            raise
        else:
            self._died(run, MonitorLifeError(f"{self.name}: task returned"))

    def _died(self, run: MonitorRun, exc: BaseException) -> None:
        run.end_clk = self._clk()
        run.end = "died"
        self._fault = exc

    def _raise_fault(self) -> None:
        run = self.runs[-1] if self.runs else None
        end_clk = run.end_clk if run is not None else None
        raise MonitorLifeError(
            f"MONITOR-LIFE FAIL: {self.name} task ended at clk={end_clk} without stop() "
            f"(epoch={self.epoch}): {self._fault!r}"
        ) from self._fault

    async def stop(self) -> None:
        """Close the open run. Raises if the task ended before this call."""
        if self._task is None:
            return
        if self._fault is not None:
            self._task = None
            self._raise_fault()
        self._stopping = True
        run = self.runs[-1]
        run.end_clk = self._clk()
        run.end = "stopped"
        self._task.cancel()
        self._task = None

    def check(self, mark_epoch: int | None = None) -> None:
        """Raise unless the record is continuous from a mark of ``mark_epoch`` to now.

        ``None`` skips the epoch check (a plain record index carries no epoch);
        the task-end check always runs.
        """
        if self._fault is not None:
            self._raise_fault()
        if mark_epoch is None:
            return
        if mark_epoch == NO_RUN:
            raise MonitorLifeError(
                f"MONITOR-LIFE FAIL: {self.name} mark was taken while no run was open "
                f"(epoch={self.epoch})"
            )
        if mark_epoch != self.epoch:
            raise MonitorLifeError(
                f"MONITOR-LIFE FAIL: {self.name} mark is from run epoch {mark_epoch}; the "
                f"monitor restarted since (epoch={self.epoch}), so the record has a gap"
            )

    def require_running(self) -> None:
        """Raise unless the task is sampling now (a bounded wait needs fresh samples)."""
        if self._fault is not None:
            self._raise_fault()
        if self._task is None:
            raise MonitorLifeError(
                f"MONITOR-LIFE FAIL: {self.name} is not running (epoch={self.epoch})"
            )
