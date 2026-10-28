# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-clock watcher of named bits of one tb_top port.

Reads one port on every rising edge of ``clk_i``, in the read-only phase, and
drives nothing. For each named bit it records the clocks of every rise and
fall and the number of clocks the bit was high. Clock ``n`` is the n-th
sampled edge after ``start``.

Typical ports: ``sep_internal_interrupts_probe_o`` (PIC source n at index
n-1), ``dma_busy_probe_o`` and ``spi_lsio_trigger_probe_o`` (approved probes,
docs/SEP_TB_ARCH.adoc).

``SepVecWatch`` reads the whole port instead and grades the exclusivity of a
rise: at each rise of an own bit, every other bit keeps the value it had one
clock before. ``pic_vector_watch`` builds one on the PIC source vector.

A bit index outside the port width raises ``BitWatchIndexError`` at ``start``
and on the first sample, so a watcher never reads another bit of the port.

A watched bit that resolves to X or Z fails the leaf with ``BIT-WATCH-XZ
FAIL`` while ``xz_fail`` is set. Verilator is 2-state.

A query over a window the watcher never sampled (not started, stopped before
the stimulus, or no clock since the mark) raises ``BitWatchIdleError``, so a
"never rose" or "never high" check cannot pass on an empty record. A query
raises ``MonitorLifeError`` (env/sep_monitor_life.py) when the watcher task
ended without ``stop``, or when the mark is from an earlier run of the
watcher, so it cannot pass on a record that a dead task left partial. The
bounded waits and ``level`` raise the same error, and ``stop`` raises it when
the task ended before it.

Usage::

    irq = SepBitWatch(dut.sep_internal_interrupts_probe_o, {"chunk": 9, "err": 10}).start()
    busy = SepBitWatch(dut.dma_busy_probe_o).start()
    m = busy.mark()
    ...write GO...
    await busy.wait_rise(m, bound=2_000)
    irq.rises_since(m, "chunk"), busy.high_clocks_since(m)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from sep_monitor_life import MonitorLife
from sep_monitor_life import MonitorLifeError as MonitorLifeError


class BitWatchXZError(AssertionError):
    """A watched bit resolved to X or Z."""


class BitWatchTimeout(AssertionError):
    """A bounded wait on a watched bit expired."""


class BitWatchIdleError(AssertionError):
    """A query covers a window in which the watcher took no sample."""


class BitWatchIndexError(AssertionError):
    """A watched bit index is outside the width of the port."""


@dataclass
class _BitRec:
    idx: int
    level: int | None = None
    rises: list[int] = field(default_factory=list)
    falls: list[int] = field(default_factory=list)
    high_clocks: int = 0


@dataclass(frozen=True)
class BitMark:
    """A point in the record: the clock, per bit the rise and high counts, and the run epoch."""

    clk: int
    rises: dict[str, int]
    high: dict[str, int]
    epoch: int | None = None


class SepBitWatch:
    """Records rises, falls and high clocks of named bits of one port."""

    def __init__(
        self,
        sig,
        bits: dict[str, int] | None = None,
        *,
        name: str | None = None,
        dut=None,
        xz_fail: bool = True,
    ) -> None:
        self.dut: Any = dut if dut is not None else cocotb.top
        self.sig = sig
        self.name = name or getattr(sig, "_name", "sig")
        self.bits = {k: _BitRec(v) for k, v in (bits or {"bit": 0}).items()}
        self._default = next(iter(self.bits)) if len(self.bits) == 1 else None
        self.xz_fail = xz_fail
        self.clk = 0
        self._width: int | None = None
        self._task: Any = None
        self.life = MonitorLife(f"BIT-WATCH {self.name}", lambda: self.clk)
        self.log = logging.getLogger("cocotb.sep_bit_watch")

    def _key(self, bit: str | None) -> str:
        key = bit if bit is not None else self._default
        if key is None:
            raise KeyError(f"{self.name}: name the bit; watched bits are {sorted(self.bits)}")
        return key

    def _mark_key(self, mark: BitMark, bit: str | None) -> str:
        key = self._key(bit)
        if key not in mark.rises:
            raise KeyError(f"{self.name}: the mark was not taken on this watcher (no bit {key})")
        return key

    def _rec(self, bit: str | None) -> _BitRec:
        return self.bits[self._key(bit)]

    def _check_width(self, width: int) -> None:
        """Raise when a watched index is negative or at or above ``width``."""
        if self._width == width:
            return
        bad = {k: r.idx for k, r in self.bits.items() if not 0 <= r.idx < width}
        if bad:
            msg = f"BIT-WATCH-INDEX FAIL: {self.name} is {width} bits wide; indices {bad}"
            self.log.error(msg)
            raise BitWatchIndexError(msg)
        self._width = width

    def start(self) -> "SepBitWatch":
        bits = self._bitstr()
        if bits:
            self._check_width(len(bits))
        if self._task is None:
            self._task = self.life.start(self._run())
        return self

    async def stop(self) -> None:
        """Close the run; raises ``MonitorLifeError`` if the task ended before."""
        self._task = None
        await self.life.stop()

    def mark(self) -> BitMark:
        return BitMark(
            self.clk,
            {k: len(r.rises) for k, r in self.bits.items()},
            {k: r.high_clocks for k, r in self.bits.items()},
            self.life.mark_epoch(),
        )

    def level(self, bit: str | None = None) -> int | None:
        """The level of the last sample (None before the first sample)."""
        self.life.check()
        return self._rec(bit).level

    def _require_sampled(self, mark: BitMark) -> None:
        self.life.check(mark.epoch)
        if self.clk <= mark.clk:
            raise BitWatchIdleError(
                f"BIT-WATCH FAIL: {self.name} took no sample after the mark "
                f"(running={self._task is not None} clk={self.clk} mark_clk={mark.clk})"
            )

    def _rises_after(self, mark: BitMark, bit: str | None) -> list[int]:
        key = self._mark_key(mark, bit)
        return self.bits[key].rises[mark.rises[key] :]

    def rise_clks_since(self, mark: BitMark, bit: str | None = None) -> list[int]:
        self._require_sampled(mark)
        return self._rises_after(mark, bit)

    def rises_since(self, mark: BitMark, bit: str | None = None) -> int:
        return len(self.rise_clks_since(mark, bit))

    def rose_since(self, mark: BitMark, bit: str | None = None) -> bool:
        return self.rises_since(mark, bit) > 0

    def fall_clks_since(self, mark: BitMark, bit: str | None = None) -> list[int]:
        self._require_sampled(mark)
        return [c for c in self._rec(bit).falls if c > mark.clk]

    def high_clocks_since(self, mark: BitMark, bit: str | None = None) -> int:
        self._require_sampled(mark)
        key = self._mark_key(mark, bit)
        return self.bits[key].high_clocks - mark.high[key]

    def any_high_since(self, mark: BitMark, bit: str | None = None) -> bool:
        return self.high_clocks_since(mark, bit) > 0

    async def wait_rise(self, mark: BitMark, bound: int, bit: str | None = None) -> int:
        """Wait at most ``bound`` clocks for a rise after ``mark``; return its clock."""
        clk = self.dut.clk_i
        for _ in range(bound + 1):
            self.life.check(mark.epoch)
            rises = self._rises_after(mark, bit)
            if rises:
                return rises[0]
            self.life.require_running()
            await RisingEdge(clk)
        raise BitWatchTimeout(
            f"{self.name}[{bit or self._default}] did not rise within {bound} clocks "
            f"after clock {mark.clk}"
        )

    async def wait_level(self, level: int, bound: int, bit: str | None = None) -> int:
        """Wait at most ``bound`` clocks for the bit to read ``level``; return the clock."""
        clk = self.dut.clk_i
        for _ in range(bound + 1):
            self.life.require_running()
            if self._rec(bit).level == level:
                return self.clk
            await RisingEdge(clk)
        raise BitWatchTimeout(
            f"{self.name}[{bit or self._default}] did not read {level} within {bound} clocks"
        )

    def _bitstr(self) -> str:
        v = self.sig.value
        s = getattr(v, "binstr", None)
        return (s if s is not None else str(v)).strip()

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            bits = self._bitstr()
            self._check_width(len(bits))
            for key, rec in self.bits.items():
                c = bits[len(bits) - 1 - rec.idx]
                if c not in "01":
                    if self.xz_fail:
                        msg = f"BIT-WATCH-XZ FAIL: {self.name}[{rec.idx}]={c} clk={self.clk}"
                        self.log.error(msg)
                        raise BitWatchXZError(msg)
                    continue
                lvl = int(c)
                if rec.level is not None and lvl != rec.level:
                    (rec.rises if lvl else rec.falls).append(self.clk)
                if lvl:
                    rec.high_clocks += 1
                rec.level = lvl


class VecWatchNoRiseError(AssertionError):
    """An exclusivity query found no rise of the own bit after the mark."""


@dataclass(frozen=True)
class VecRise:
    """One rise of an own bit: its clock and the vector one clock before and at the rise."""

    clk: int
    before: int
    after: int


@dataclass(frozen=True)
class VecMark:
    """A point in the record of a vector watcher: the clock, per own bit the rise count, the epoch."""

    clk: int
    rises: dict[str, int]
    epoch: int | None = None


class SepVecWatch:
    """Per-clock watcher of a whole vector port for the exclusivity of a bit's rise.

    Reads the port on every rising edge of ``clk_i``, in the read-only phase,
    and drives nothing. For each named own bit it records every rise with the
    vector one clock before the rise and at the rise. :meth:`smears_since`
    gives, per rise after a mark, the other bits whose value at the rise
    differs from their value one clock before. Bits of ``ignore_mask`` (for the
    PIC vector, the six sources with an unstated idle level) and of the
    caller's same-clock set are not compared.

    A bit outside ``ignore_mask`` that resolves to X or Z fails the leaf with
    ``VEC-WATCH-XZ FAIL`` while ``xz_fail`` is set; an ignored bit reads as 0.
    A query over a window with no sample raises ``BitWatchIdleError``, an
    exclusivity query with no rise of the own bit raises
    ``VecWatchNoRiseError``, and a query on a dead or earlier run raises
    ``MonitorLifeError``, so an exclusivity check cannot pass on an empty
    record.

    Usage::

        vec = pic_vector_watch({"own": vec_bit(34)}).start()
        m = vec.mark()
        ...stimulus that raises source 34...
        bad = vec.smears_since(m, "own", same_clock=vec_mask([33]))
    """

    def __init__(
        self,
        sig,
        own: dict[str, int],
        *,
        ignore_mask: int = 0,
        name: str | None = None,
        dut=None,
        xz_fail: bool = True,
    ) -> None:
        if not own:
            raise ValueError("SepVecWatch needs at least one own bit")
        self.dut: Any = dut if dut is not None else cocotb.top
        self.sig = sig
        self.name = name or getattr(sig, "_name", "sig")
        self.own = dict(own)
        self.ignore_mask = ignore_mask
        self.xz_fail = xz_fail
        self.clk = 0
        self.prev: int | None = None
        self.rises: dict[str, list[VecRise]] = {k: [] for k in self.own}
        self._width: int | None = None
        self._task: Any = None
        self.life = MonitorLife(f"VEC-WATCH {self.name}", lambda: self.clk)
        self.log = logging.getLogger("cocotb.sep_bit_watch")

    def _check_width(self, width: int) -> None:
        if self._width == width:
            return
        bad = {k: i for k, i in self.own.items() if not 0 <= i < width}
        if bad:
            msg = f"BIT-WATCH-INDEX FAIL: {self.name} is {width} bits wide; indices {bad}"
            self.log.error(msg)
            raise BitWatchIndexError(msg)
        self._width = width

    def start(self) -> "SepVecWatch":
        v = self.sig.value
        s = getattr(v, "binstr", None)
        bits = (s if s is not None else str(v)).strip()
        if bits:
            self._check_width(len(bits))
        if self._task is None:
            self._task = self.life.start(self._run())
        return self

    async def stop(self) -> None:
        """Close the run; raises ``MonitorLifeError`` if the task ended before."""
        self._task = None
        await self.life.stop()

    def mark(self) -> VecMark:
        return VecMark(self.clk, {k: len(r) for k, r in self.rises.items()}, self.life.mark_epoch())

    def _key(self, mark: VecMark, key: str) -> str:
        if key not in self.own:
            raise KeyError(f"{self.name}: no own bit {key}; own bits are {sorted(self.own)}")
        if key not in mark.rises:
            raise KeyError(f"{self.name}: the mark was not taken on this watcher (no bit {key})")
        return key

    def rises_since(self, mark: VecMark, key: str) -> list[VecRise]:
        """Every rise of own bit ``key`` after ``mark``."""
        self.life.check(mark.epoch)
        if self.clk <= mark.clk:
            raise BitWatchIdleError(
                f"VEC-WATCH FAIL: {self.name} took no sample after the mark "
                f"(running={self._task is not None} clk={self.clk} mark_clk={mark.clk})"
            )
        key = self._key(mark, key)
        return self.rises[key][mark.rises[key] :]

    def smears_since(self, mark: VecMark, key: str, same_clock: int = 0) -> list[tuple[int, int]]:
        """``(clock, changed mask)`` of each rise of ``key`` after ``mark`` where another bit moved.

        A bit moved when its value at the rise differs from its value one clock
        before. The own bit, ``ignore_mask`` and ``same_clock`` are not
        compared. Raises ``VecWatchNoRiseError`` when ``key`` did not rise
        after the mark.
        """
        rises = self.rises_since(mark, key)
        if not rises:
            raise VecWatchNoRiseError(
                f"VEC-WATCH FAIL: {self.name}[{self.own[key]}] ({key}) did not rise after clock {mark.clk}"
            )
        skip = (1 << self.own[key]) | self.ignore_mask | same_clock
        out = []
        for r in rises:
            moved = (r.before ^ r.after) & ~skip
            if moved:
                out.append((r.clk, moved))
        return out

    def _read(self) -> int:
        v = self.sig.value
        s = getattr(v, "binstr", None)
        bits = (s if s is not None else str(v)).strip()
        self._check_width(len(bits))
        word = 0
        for pos, c in enumerate(reversed(bits)):
            if c == "1":
                word |= 1 << pos
            elif c != "0" and self.xz_fail and not (self.ignore_mask >> pos) & 1:
                msg = f"VEC-WATCH-XZ FAIL: {self.name}[{pos}]={c} clk={self.clk}"
                self.log.error(msg)
                raise BitWatchXZError(msg)
        return word

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            cur = self._read()
            if self.prev is not None:
                for key, idx in self.own.items():
                    if (cur >> idx) & 1 and not (self.prev >> idx) & 1:
                        self.rises[key].append(VecRise(self.clk, self.prev, cur))
            self.prev = cur


def pic_vector_watch(own: dict[str, int], *, dut=None) -> SepVecWatch:
    """A :class:`SepVecWatch` on ``sep_internal_interrupts_probe_o`` (PIC source n at bit n-1).

    The six sources whose idle level ``hw/sys/sep/doc/interrupts.adoc`` does
    not state are not compared (``env/sep_pic_map.VEC_IDLE_MASK``).
    """
    from sep_pic_map import VEC_IDLE_MASK

    top: Any = dut if dut is not None else cocotb.top
    return SepVecWatch(
        top.sep_internal_interrupts_probe_o, own, ignore_mask=VEC_IDLE_MASK, name="pic_vec", dut=top
    )
