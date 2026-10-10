# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-core-clock sampler of the SPI host pad ports.

Reads ``spi_cs_n_o``, ``spi_sck_o`` and ``spi_mosi_o`` of ``tb_top`` (the
approved SPI host pad ports, docs/SEP_TB_ARCH.adoc) on every rising edge of
``clk_i``, in the read-only phase, and drives nothing. Clock ``n`` is the n-th
sampled edge after ``start``; every time value here is a clock index, so every
time relation is in core clocks.

Records:

* chip-select-low windows (``CsWindow``): the clock of the first low sample
  (``start``) and of the first high sample after it (``end``); the sck level at
  ``start``; every sck edge as (clock, new level); every ``spi_mosi_o`` change.
  A leading edge is an sck edge that leaves the idle level. The idle level is
  the value given to ``set_idle_level`` (the CPOL that the leaf wrote) or,
  when none is given, the sck level at ``start``. ``lead`` is the clocks from
  ``start`` to the first sck edge and ``trail`` the clocks from the last sck
  edge to ``end``. ``periods`` are the clocks between neighbouring leading
  edges.
* chip-select-high windows (``CsHighWindow``): the start and end clocks and the
  set of sck levels sampled in the window.
* every sck edge and every mosi change of the run, chip select high or low.

A chip select or sck sample that resolves to X or Z fails the leaf with
``SPI-PAD-XZ FAIL`` while ``xz_fail`` is set. Verilator is 2-state.

Usage::

    pads = SepSpiPadSampler().start()
    mark = pads.mark()
    ...write COMMAND...
    wins = await pads.wait_windows(1, mark, bound=200_000)
    wins[0].leading_edges, wins[0].periods, wins[0].lead, wins[0].trail
    await pads.stop()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge


class SpiPadXZError(AssertionError):
    """A chip select or sck sample resolved to X or Z."""


class SpiPadTimeout(AssertionError):
    """A bounded wait on the pad sampler expired."""


@dataclass
class CsWindow:
    """One chip-select-low window."""

    start: int
    idle_level: int
    sck_at_start: int
    end: int | None = None
    edges: list[tuple[int, int]] = field(default_factory=list)
    mosi_changes: list[int] = field(default_factory=list)
    # Clocks in the window on which spi_mosi_o was X or Z. A change count
    # over such a window is incomplete, so a check on MOSI changes needs 0.
    mosi_xz: int = 0

    @property
    def complete(self) -> bool:
        return self.end is not None

    @property
    def leading_edge_clks(self) -> list[int]:
        return [c for c, lvl in self.edges if lvl != self.idle_level]

    @property
    def trailing_edge_clks(self) -> list[int]:
        return [c for c, lvl in self.edges if lvl == self.idle_level]

    @property
    def leading_edges(self) -> int:
        """The sck cycle count: leading edges while chip select is low."""
        return len(self.leading_edge_clks)

    @property
    def toggles(self) -> int:
        return len(self.edges)

    @property
    def periods(self) -> list[int]:
        lead = self.leading_edge_clks
        return [b - a for a, b in zip(lead, lead[1:])]

    @property
    def lead(self) -> int | None:
        return self.edges[0][0] - self.start if self.edges else None

    @property
    def trail(self) -> int | None:
        if self.end is None or not self.edges:
            return None
        return self.end - self.edges[-1][0]

    def fmt(self) -> str:
        return (
            f"cs_low[{self.start}..{self.end}] idle={self.idle_level} "
            f"lead_edges={self.leading_edges} toggles={self.toggles} "
            f"lead={self.lead} trail={self.trail}"
        )


@dataclass
class CsHighWindow:
    """One chip-select-high window between two low windows (or after the last)."""

    start: int
    end: int | None = None
    sck_levels: set[int] = field(default_factory=set)
    sck_toggles: int = 0


@dataclass(frozen=True)
class PadMark:
    """A point in the sampler record: the clock and the window counts at that clock."""

    clk: int
    n_low: int
    n_high: int
    n_edges: int
    n_mosi: int


class SepSpiPadSampler:
    """Samples the SPI host pads on each ``clk_i`` rising edge until stopped."""

    def __init__(self, dut=None, *, xz_fail: bool = True, keep_edges: bool = True) -> None:
        self.dut: Any = dut if dut is not None else cocotb.top
        self.xz_fail = xz_fail
        # False keeps only per-window edges; the run-wide edge list stays empty.
        self.keep_edges = keep_edges
        self._cs = self.dut.spi_cs_n_o
        self._sck = self.dut.spi_sck_o
        self._mosi = self.dut.spi_mosi_o
        self._task: Any = None
        self._idle: int | None = None
        self.clk = 0
        self.low: list[CsWindow] = []
        self.high: list[CsHighWindow] = []
        self.sck_edges: list[tuple[int, int]] = []
        self.mosi_changes: list[int] = []
        self._cs_level: int | None = None
        self._sck_level: int | None = None
        self._mosi_level: int | None = None
        self.log = logging.getLogger("cocotb.sep_spi_pad_sampler")

    # ---- control ---------------------------------------------------------
    def set_idle_level(self, level: int | None) -> None:
        """The sck idle level (CPOL) for windows that start after this call."""
        self._idle = None if level is None else int(level) & 1

    def start(self) -> "SepSpiPadSampler":
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def clear(self) -> None:
        """Drop the record. An open window stays open from the current clock."""
        open_low = self.low[-1] if self.low and self.low[-1].end is None else None
        open_high = self.high[-1] if self.high and self.high[-1].end is None else None
        self.low = []
        self.high = []
        self.sck_edges = []
        self.mosi_changes = []
        if open_low is not None:
            self.low.append(CsWindow(self.clk, open_low.idle_level, self._sck_level or 0))
        if open_high is not None:
            self.high.append(CsHighWindow(self.clk, sck_levels={self._sck_level or 0}))

    def mark(self) -> PadMark:
        return PadMark(
            self.clk, len(self.low), len(self.high), len(self.sck_edges), len(self.mosi_changes)
        )

    def now(self) -> int:
        """The clock index of the last sample."""
        return self.clk

    def cs_low(self) -> bool:
        """True when the last sample of chip select was low."""
        return self._cs_level == 0

    # ---- queries ---------------------------------------------------------
    def windows_since(self, mark: PadMark, *, complete_only: bool = True) -> list[CsWindow]:
        """Chip-select-low windows that started after ``mark``."""
        return [w for w in self.low if w.start > mark.clk and (w.complete or not complete_only)]

    def count_windows(self, mark: PadMark) -> int:
        return len(self.windows_since(mark))

    def high_windows_since(
        self, mark: PadMark, *, complete_only: bool = False
    ) -> list[CsHighWindow]:
        return [
            w for w in self.high if w.start > mark.clk and (w.end is not None or not complete_only)
        ]

    def gaps_since(self, mark: PadMark) -> list[int]:
        """Chip-select-high clocks between neighbouring low windows after ``mark``."""
        wins = self.windows_since(mark)
        return [b.start - a.end for a, b in zip(wins, wins[1:]) if a.end is not None]

    def sck_edges_between(self, c0: int, c1: int) -> list[tuple[int, int]]:
        """Every sck edge (clock, new level) with ``c0 <= clock < c1``."""
        return [(c, lvl) for c, lvl in self.sck_edges if c0 <= c < c1]

    def mosi_changes_between(self, c0: int, c1: int) -> list[int]:
        return [c for c in self.mosi_changes if c0 <= c < c1]

    def leading_edges_since(self, mark: PadMark) -> int:
        """Leading sck edges in every low window that is open or started after ``mark``."""
        total = 0
        for w in self.low:
            if w.end is not None and w.end <= mark.clk:
                continue
            total += sum(1 for c in w.leading_edge_clks if c > mark.clk)
        return total

    # ---- bounded waits ---------------------------------------------------
    async def wait_windows(self, n: int, mark: PadMark, bound: int) -> list[CsWindow]:
        """Wait at most ``bound`` clocks for ``n`` complete low windows after ``mark``."""
        clk = self.dut.clk_i
        for _ in range(bound + 1):
            wins = self.windows_since(mark)
            if len(wins) >= n:
                return wins[:n]
            await RisingEdge(clk)
        raise SpiPadTimeout(
            f"SPI pads: {len(self.windows_since(mark))} of {n} chip-select-low windows "
            f"complete within {bound} clocks after clock {mark.clk}"
        )

    async def wait_leading_edges(self, n: int, mark: PadMark, bound: int) -> int:
        """Wait at most ``bound`` clocks for ``n`` leading sck edges after ``mark``."""
        clk = self.dut.clk_i
        for _ in range(bound + 1):
            got = self.leading_edges_since(mark)
            if got >= n:
                return got
            await RisingEdge(clk)
        raise SpiPadTimeout(
            f"SPI pads: {self.leading_edges_since(mark)} of {n} leading sck edges "
            f"within {bound} clocks after clock {mark.clk}"
        )

    # ---- sampling --------------------------------------------------------
    def _bit(self, sig, name: str, fail: bool) -> int | None:
        v = sig.value
        if v.is_resolvable:
            return int(v) & 1
        if fail and self.xz_fail:
            msg = f"SPI-PAD-XZ FAIL: {name}={v} clk={self.clk}"
            self.log.error(msg)
            raise SpiPadXZError(msg)
        return None

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            cs = self._bit(self._cs, "spi_cs_n_o", True)
            sck = self._bit(self._sck, "spi_sck_o", True)
            mosi = self._bit(self._mosi, "spi_mosi_o", False)
            if cs is None or sck is None:
                continue
            now = self.clk
            if cs != self._cs_level:
                if cs == 0:
                    if self.high and self.high[-1].end is None:
                        self.high[-1].end = now
                    # The level before this clock, so an sck edge on the
                    # chip-select clock itself counts as an edge of the window.
                    before = sck if self._sck_level is None else self._sck_level
                    idle = self._idle if self._idle is not None else before
                    self.low.append(CsWindow(now, idle, before))
                else:
                    if self.low and self.low[-1].end is None:
                        self.low[-1].end = now
                    self.high.append(CsHighWindow(now, sck_levels={sck}))
                self._cs_level = cs
            if self._sck_level is not None and sck != self._sck_level:
                if self.keep_edges:
                    self.sck_edges.append((now, sck))
                if cs == 0 and self.low:
                    self.low[-1].edges.append((now, sck))
                elif self.high:
                    self.high[-1].sck_toggles += 1
            if cs == 1 and self.high:
                self.high[-1].sck_levels.add(sck)
            if mosi is None and cs == 0 and self.low:
                self.low[-1].mosi_xz += 1
            if mosi is not None and self._mosi_level is not None and mosi != self._mosi_level:
                self.mosi_changes.append(now)
                if cs == 0 and self.low:
                    self.low[-1].mosi_changes.append(now)
            self._sck_level = sck
            if mosi is not None:
                self._mosi_level = mosi
