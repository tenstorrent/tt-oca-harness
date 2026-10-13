# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sub-cycle edge timing and pin edge counting.

``SepEdgeTimer`` records every value change of one signal with its simulation
time in ps. ``SepPinEdgeCounter`` counts the rising edges of clock pins
(``clk_i``, ``clk_ref_i``, ``clk_wdt_i``) and keeps the times of the last
edges of each pin. Both drive nothing.

The phase functions place an event time against the rising edges of a
reference clock: the offset after the last edge at or before the event, the
signed offset to the nearest edge, and the phase in percent of the period.
These are measurements. A leaf logs them; a calibration value places stimulus
and is never an expected value.

Verilator is 2-state and its delta ordering differs from VCS, so a check that
grades a sub-cycle phase runs on VCS.

Usage::

    clk = SepPinEdgeCounter(("clk_i", "clk_wdt_i")).start()
    rst = SepEdgeTimer(dut.dbg_sep_reset_n_o).start()
    ...stimulus...
    t = rst.rises()[-1]
    off = clk.offset_after_ps("clk_i", t)
    pct = phase_pct(off, period_ps)
"""

from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

import cocotb
from cocotb.triggers import Edge, RisingEdge
from cocotb.utils import get_sim_time


@dataclass(frozen=True)
class TimedChange:
    """One value change of a timed signal."""

    t_ps: int
    value: int | None
    """The new value; None when it resolves to X or Z."""


def _now_ps() -> int:
    return int(get_sim_time("ps"))


def _value(sig) -> int | None:
    v = sig.value
    return int(v) if v.is_resolvable else None


def phase_pct(offset_ps: float, period_ps: float) -> float:
    """``offset_ps`` in percent of ``period_ps``."""
    if period_ps <= 0:
        raise ValueError("period_ps must be positive")
    return 100.0 * offset_ps / period_ps


def offset_after_ps(t_ps: int, edges_ps: list[int]) -> int | None:
    """Time from the last edge at or before ``t_ps`` (None if none is recorded)."""
    i = bisect.bisect_right(edges_ps, t_ps)
    if i == 0:
        return None
    return t_ps - edges_ps[i - 1]


def nearest_edge_offset_ps(t_ps: int, edges_ps: list[int]) -> int | None:
    """Signed time from the nearest edge to ``t_ps`` (negative: before the edge)."""
    if not edges_ps:
        return None
    i = bisect.bisect_left(edges_ps, t_ps)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(edges_ps):
            d = t_ps - edges_ps[j]
            if best is None or abs(d) < abs(best):
                best = d
    return best


class SepEdgeTimer:
    """Records the value changes of one signal with their times in ps."""

    def __init__(self, sig, *, name: str | None = None, keep: int | None = None) -> None:
        self.sig = sig
        self.name = name or getattr(sig, "_name", "sig")
        self.changes: deque[TimedChange] = deque(maxlen=keep)
        self._task: Any = None

    def start(self) -> "SepEdgeTimer":
        if self._task is None:
            self.changes.append(TimedChange(_now_ps(), _value(self.sig)))
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        while True:
            await Edge(self.sig)
            self.changes.append(TimedChange(_now_ps(), _value(self.sig)))

    def since(self, t_ps: int) -> list[TimedChange]:
        """The changes at or after ``t_ps``."""
        return [c for c in self.changes if c.t_ps >= t_ps]

    def rises(self, since_ps: int = 0) -> list[int]:
        """Times of 0 to 1 changes of a 1-bit signal."""
        return self._edges(since_ps, 0, 1)

    def falls(self, since_ps: int = 0) -> list[int]:
        """Times of 1 to 0 changes of a 1-bit signal."""
        return self._edges(since_ps, 1, 0)

    def _edges(self, since_ps: int, frm: int, to: int) -> list[int]:
        out = []
        prev = None
        for c in self.changes:
            if prev is not None and prev == frm and c.value == to and c.t_ps >= since_ps:
                out.append(c.t_ps)
            prev = c.value
        return out

    def value_at(self, t_ps: int) -> int | None:
        """The value after every change at or before ``t_ps``."""
        val = None
        for c in self.changes:
            if c.t_ps > t_ps:
                break
            val = c.value
        return val

    def fmt(self, since_ps: int = 0, limit: int = 16) -> str:
        """A one-line value-change log for an ``OBS-`` line."""
        items = self.since(since_ps)[:limit]
        body = " ".join(f"{c.t_ps}ps={'X' if c.value is None else hex(c.value)}" for c in items)
        return f"{self.name}[{body}]"


class SepPinEdgeCounter:
    """Counts rising edges of clock pins and keeps the last edge times."""

    def __init__(self, pins: Iterable[str], *, dut: Any = None, keep: int = 4096) -> None:
        self.dut = dut if dut is not None else cocotb.top
        self.pins = tuple(pins)
        self.count: dict[str, int] = {p: 0 for p in self.pins}
        self.edges: dict[str, deque[int]] = {p: deque(maxlen=keep) for p in self.pins}
        self._tasks: list[Any] = []

    def start(self) -> "SepPinEdgeCounter":
        if not self._tasks:
            self._tasks = [cocotb.start_soon(self._run(p)) for p in self.pins]
        return self

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    async def _run(self, pin: str) -> None:
        sig = getattr(self.dut, pin)
        while True:
            await RisingEdge(sig)
            self.count[pin] += 1
            self.edges[pin].append(_now_ps())

    def mark(self) -> dict[str, int]:
        return dict(self.count)

    def since(self, mark: dict[str, int], pin: str) -> int:
        """Rising edges of ``pin`` after ``mark``."""
        return self.count[pin] - mark[pin]

    def edge_times(self, pin: str) -> list[int]:
        return list(self.edges[pin])

    def offset_after_ps(self, pin: str, t_ps: int) -> int | None:
        return offset_after_ps(t_ps, self.edge_times(pin))

    def nearest_edge_offset_ps(self, pin: str, t_ps: int) -> int | None:
        return nearest_edge_offset_ps(t_ps, self.edge_times(pin))

    def period_ps(self, pin: str) -> int | None:
        """The last measured period of ``pin`` (None before two edges)."""
        e = self.edges[pin]
        return e[-1] - e[-2] if len(e) >= 2 else None


if __name__ == "__main__":
    # Self-check of the phase arithmetic (no simulator).
    edges = [0, 1000, 2000, 3000]
    assert offset_after_ps(2500, edges) == 500
    assert offset_after_ps(2000, edges) == 0
    assert offset_after_ps(-1, edges) is None
    assert nearest_edge_offset_ps(2900, edges) == -100
    assert nearest_edge_offset_ps(2100, edges) == 100
    assert phase_pct(250, 1000) == 25.0
    print("sep_edge_timer self-check PASS")
