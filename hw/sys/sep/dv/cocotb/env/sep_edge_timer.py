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

A pass through X or Z between two known values counts as the transition
between them: ``1 -> X -> 0`` is a fall at the time the net resolves to 0, so
an absence check ("no fall in the window") fails on it. ``xz_episodes`` lists
every stretch at X or Z with the known values around it, for the leaf to log.

A ``SepEdgeTimer`` query covers the window from ``since_ps`` (default: the
start of the last run) to ``until_ps`` (default: now). It raises
``SepEdgeIdleError`` unless one run of the timer covers the whole window: the
timer was started at or before ``since_ps`` and was not stopped or restarted
before ``until_ps``, and no change in the window was dropped from a bounded
record. A ``SepPinEdgeCounter.since`` over a window the counter did not sample
for its whole length (not running at the mark, or stopped or restarted after
it) also raises ``SepEdgeIdleError``. So a count or an absence cannot pass on an
empty record. A leaf that stops a timer before it grades passes the end of its
graded window as ``until_ps``.

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


class SepEdgeIdleError(AssertionError):
    """A query over a window the recorder did not sample."""


@dataclass(frozen=True)
class XzEpisode:
    """One stretch at X or Z of a timed signal (or of the selected bit)."""

    t_start_ps: int
    t_end_ps: int | None
    """The time the value resolves again; None while it is still X or Z."""
    before: int | None
    """The last known value before the stretch; None if none is recorded."""
    after: int | None
    """The known value that ends the stretch; None while it is still X or Z."""


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
        self._runs: list[list[int | None]] = []
        """[start, stop] of each run in ps; stop is None while the run goes on."""
        self._dropped = False

    def start(self) -> "SepEdgeTimer":
        if self._task is None:
            t = _now_ps()
            self._runs.append([t, None])
            self._append(TimedChange(t, _value(self.sig)))
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
            self._runs[-1][1] = _now_ps()

    def _append(self, c: TimedChange) -> None:
        if self.changes.maxlen is not None and len(self.changes) == self.changes.maxlen:
            self._dropped = True
        self.changes.append(c)

    async def _run(self) -> None:
        while True:
            await Edge(self.sig)
            self._append(TimedChange(_now_ps(), _value(self.sig)))

    def _window(self, since_ps: int | None, until_ps: int | None) -> tuple[int, int]:
        """The queried window; raises unless one run covers all of it."""
        if not self._runs:
            raise SepEdgeIdleError(f"SEP-EDGE FAIL: {self.name} timer was never started")
        lo = self._runs[-1][0] if since_ps is None else since_ps
        running = self._task is not None
        hi = until_ps if until_ps is not None else (_now_ps() if running else None)
        if hi is None:
            raise SepEdgeIdleError(
                f"SEP-EDGE FAIL: {self.name} timer stopped at {self._runs[-1][1]} ps; the query "
                "names no window end (until_ps), so the timer did not run through it"
            )
        if hi < lo:
            raise ValueError(f"{self.name}: window end {hi} ps is before its start {lo} ps")
        for start, stop in self._runs:
            if start <= lo and (stop is None or stop >= hi):
                break
        else:
            raise SepEdgeIdleError(
                f"SEP-EDGE FAIL: {self.name} timer did not run through the window "
                f"{lo}-{hi} ps (runs {self._runs})"
            )
        if self._dropped and self.changes and self.changes[0].t_ps > lo:
            raise SepEdgeIdleError(
                f"SEP-EDGE FAIL: {self.name} record dropped changes after {lo} ps "
                f"(keep={self.changes.maxlen})"
            )
        return lo, hi

    def since(self, t_ps: int | None = None, *, until_ps: int | None = None) -> list[TimedChange]:
        """The changes in the window from ``t_ps`` to ``until_ps``."""
        lo, hi = self._window(t_ps, until_ps)
        return [c for c in self.changes if lo <= c.t_ps <= hi]

    def rises(
        self, since_ps: int | None = None, *, until_ps: int | None = None, bit: int | None = None
    ) -> list[int]:
        """Times of 0 to 1 transitions in the window (of ``bit``, or of a 1-bit signal).

        A ``0 -> X/Z -> 1`` pass counts, at the time the value resolves to 1.
        """
        return self._edges(since_ps, until_ps, 0, 1, bit)

    def falls(
        self, since_ps: int | None = None, *, until_ps: int | None = None, bit: int | None = None
    ) -> list[int]:
        """Times of 1 to 0 transitions in the window (of ``bit``, or of a 1-bit signal).

        A ``1 -> X/Z -> 0`` pass counts, at the time the value resolves to 0.
        """
        return self._edges(since_ps, until_ps, 1, 0, bit)

    def _values(self, bit: int | None, hi: int) -> list[tuple[int, int | None]]:
        vals = [c for c in self.changes if c.t_ps <= hi]
        if bit is None:
            return [(c.t_ps, c.value) for c in vals]
        return [(c.t_ps, None if c.value is None else (c.value >> bit) & 1) for c in vals]

    def _edges(
        self, since_ps: int | None, until_ps: int | None, frm: int, to: int, bit: int | None
    ) -> list[int]:
        lo, hi = self._window(since_ps, until_ps)
        out = []
        known = None
        for t_ps, v in self._values(bit, hi):
            if v is None:
                continue
            if known == frm and v == to and t_ps >= lo:
                out.append(t_ps)
            known = v
        return out

    def xz_episodes(
        self, since_ps: int | None = None, *, until_ps: int | None = None, bit: int | None = None
    ) -> list[XzEpisode]:
        """Every stretch at X or Z that ends in the window (or is still open at its end)."""
        lo, hi = self._window(since_ps, until_ps)
        out = []
        known = None
        start = None
        for t_ps, v in self._values(bit, hi):
            if v is None:
                if start is None:
                    start = (t_ps, known)
                continue
            if start is not None:
                if t_ps >= lo:
                    out.append(XzEpisode(start[0], t_ps, start[1], v))
                start = None
            known = v
        if start is not None:
            out.append(XzEpisode(start[0], None, start[1], None))
        return out

    def value_at(self, t_ps: int) -> int | None:
        """The value after every change at or before ``t_ps``."""
        self._window(t_ps, t_ps)
        val = None
        for c in self.changes:
            if c.t_ps > t_ps:
                break
            val = c.value
        return val

    def fmt(
        self, since_ps: int | None = None, limit: int = 16, *, until_ps: int | None = None
    ) -> str:
        """A one-line value-change log for an ``OBS-`` line."""
        items = self.since(since_ps, until_ps=until_ps)[:limit]
        body = " ".join(f"{c.t_ps}ps={'X' if c.value is None else hex(c.value)}" for c in items)
        return f"{self.name}[{body}]"


@dataclass(frozen=True)
class PinMark:
    """A point in a ``SepPinEdgeCounter`` record."""

    epoch: int
    """The counter run the mark was taken in; 0 when the counter was not running."""
    count: dict[str, int]


class SepPinEdgeCounter:
    """Counts rising edges of clock pins and keeps the last edge times."""

    def __init__(self, pins: Iterable[str], *, dut: Any = None, keep: int = 4096) -> None:
        self.dut = dut if dut is not None else cocotb.top
        self.pins = tuple(pins)
        self.count: dict[str, int] = {p: 0 for p in self.pins}
        self.edges: dict[str, deque[int]] = {p: deque(maxlen=keep) for p in self.pins}
        self._tasks: list[Any] = []
        self._epoch = 0

    def start(self) -> "SepPinEdgeCounter":
        if not self._tasks:
            self._epoch += 1
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

    def mark(self) -> PinMark:
        """The edge counts now, with the run the counter is in (0: not running)."""
        return PinMark(self._epoch if self._tasks else 0, dict(self.count))

    def since(self, mark: PinMark, pin: str) -> int:
        """Rising edges of ``pin`` after ``mark``.

        Raises ``SepEdgeIdleError`` unless the counter ran from the mark to now
        without a stop.
        """
        running = self._epoch if self._tasks else 0
        if mark.epoch == 0 or running != mark.epoch:
            raise SepEdgeIdleError(
                f"SEP-EDGE FAIL: pin counter did not sample {pin} for the whole window "
                f"(mark run={mark.epoch} current run={running})"
            )
        return self.count[pin] - mark.count[pin]

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
    tm = SepEdgeTimer(None, name="t")
    tm.changes.extend(
        TimedChange(t, v) for t, v in ((0, 1), (10, None), (20, 0), (30, 1), (40, None), (50, 1))
    )
    tm._runs = [[0, 60]]
    assert tm.falls(until_ps=60) == [20] and tm.rises(until_ps=60) == [30]
    assert tm.xz_episodes(15, until_ps=60) == [XzEpisode(10, 20, 1, 0), XzEpisode(40, 50, 1, 1)]
    assert tm.value_at(25) == 0
    for args in ((None, None), (0, 70)):
        try:
            tm.falls(args[0], until_ps=args[1])
        except SepEdgeIdleError:
            pass
        else:
            raise AssertionError(f"a query past the stop must raise: {args}")
    tm._runs = [[0, 25], [35, None]]
    try:
        tm.falls(20, until_ps=40)
    except SepEdgeIdleError:
        pass
    else:
        raise AssertionError("a window across a restart must raise")
    print("sep_edge_timer self-check PASS")
