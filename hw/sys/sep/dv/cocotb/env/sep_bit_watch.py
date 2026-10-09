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

A watched bit that resolves to X or Z fails the leaf with ``BIT-WATCH-XZ
FAIL`` while ``xz_fail`` is set. Verilator is 2-state.

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


class BitWatchXZError(AssertionError):
    """A watched bit resolved to X or Z."""


class BitWatchTimeout(AssertionError):
    """A bounded wait on a watched bit expired."""


@dataclass
class _BitRec:
    idx: int
    level: int | None = None
    rises: list[int] = field(default_factory=list)
    falls: list[int] = field(default_factory=list)
    high_clocks: int = 0


@dataclass(frozen=True)
class BitMark:
    """A point in the record: the clock and, per bit, the rise and high counts."""

    clk: int
    rises: dict[str, int]
    high: dict[str, int]


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
        self._task: Any = None
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

    def start(self) -> "SepBitWatch":
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def mark(self) -> BitMark:
        return BitMark(
            self.clk,
            {k: len(r.rises) for k, r in self.bits.items()},
            {k: r.high_clocks for k, r in self.bits.items()},
        )

    def level(self, bit: str | None = None) -> int | None:
        """The level of the last sample (None before the first sample)."""
        return self._rec(bit).level

    def rise_clks_since(self, mark: BitMark, bit: str | None = None) -> list[int]:
        key = self._mark_key(mark, bit)
        return self.bits[key].rises[mark.rises[key] :]

    def rises_since(self, mark: BitMark, bit: str | None = None) -> int:
        return len(self.rise_clks_since(mark, bit))

    def rose_since(self, mark: BitMark, bit: str | None = None) -> bool:
        return self.rises_since(mark, bit) > 0

    def fall_clks_since(self, mark: BitMark, bit: str | None = None) -> list[int]:
        return [c for c in self._rec(bit).falls if c > mark.clk]

    def high_clocks_since(self, mark: BitMark, bit: str | None = None) -> int:
        key = self._mark_key(mark, bit)
        return self.bits[key].high_clocks - mark.high[key]

    def any_high_since(self, mark: BitMark, bit: str | None = None) -> bool:
        return self.high_clocks_since(mark, bit) > 0

    async def wait_rise(self, mark: BitMark, bound: int, bit: str | None = None) -> int:
        """Wait at most ``bound`` clocks for a rise after ``mark``; return its clock."""
        clk = self.dut.clk_i
        for _ in range(bound + 1):
            rises = self.rise_clks_since(mark, bit)
            if rises:
                return rises[0]
            await RisingEdge(clk)
        raise BitWatchTimeout(
            f"{self.name}[{bit or self._default}] did not rise within {bound} clocks "
            f"after clock {mark.clk}"
        )

    async def wait_level(self, level: int, bound: int, bit: str | None = None) -> int:
        """Wait at most ``bound`` clocks for the bit to read ``level``; return the clock."""
        clk = self.dut.clk_i
        for _ in range(bound + 1):
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
