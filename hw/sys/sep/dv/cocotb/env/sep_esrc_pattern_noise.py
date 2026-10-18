# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Exact-pattern noise driver of the 12 ESRC lanes.

The driver writes ``esrc_noise_ext_i`` (bit j = lane j), which ``tb_top``
forces into the decorrelator input of each lane under ``+esrc_noise_force``
(docs/SEP_TB_ARCH.adoc, ESRC noise force). It never runs together with the
DRBG scoreboard (``env/sep_drbg_scoreboard.py``), which drives the same port.

Words. A word is one strobe period of ``esrc_decor_valid_o``. The driver
counts strobes in the read-only phase after each rising edge of ``clk_i``. It
changes the lane bits only in the clock of a strobe, after the strobe was
sampled, so the decorrelator takes the new bits from the next rising edge on
and holds them to the next strobe. Word 0 is the word that ``start`` applies;
after strobe s the lanes carry word s. With ``DECORRELATOR_CTRL.BYPASS`` set
and the reset byte period (longer than the 29-stage chain), the byte that a
lane shows at strobe s + 1 is the bit of word s in all eight bits (0xFF or
0x00).

Patterns. Each lane carries one pattern, a function of the word index n:

* ``Stuck(v)``: v on every word;
* ``Balanced(mask, perm)``: the parity of ``mask & perm[n % 64]``; 32 ones per
  64 words;
* ``Ones(name, positions)``: 1 at the word positions (mod 64) in the set;
  ``bias_lane`` draws 45 (``bias70``) or 19 (``bias30``) positions;
* ``Square(length, phase)``: runs of exactly ``length`` zeros and ones;
* ``Alternate(start)``: the bit changes on every word.

``balanced_lanes`` draws 12 different odd-weight 6-bit masks and one
permutation of 0 to 63. The XOR of two odd-weight masks has even weight, so no
mask is the XOR of two others. Every draw comes from the ``SepSeededRng`` the
leaf passes, so a seed replays the same patterns; ``describe`` gives the text
the leaf logs in its plan.

Lane-byte control. With ``byte_check`` on, at each strobe the driver compares
the 12 lane bytes of ``esrc_decor_bytes_o`` (lane j at bits 8j+7:8j) with the
bit that lane held for the whole word before the strobe: 0xFF for 1, 0x00 for
0. A word that ``start`` or an immediate ``set_lanes`` applied in mid-period is
not whole and is not compared. ``byte_control`` returns the compared and
mismatched counts; the leaf logs ``CTRL-MISSING`` and fails on a mismatch or on
no compare. A strobe or byte bit that resolves to X or Z fails the leaf with
``ESRC-NOISE-XZ FAIL``.

Word marks. ``mark`` returns the current word index and ``words_since`` the
strobes after a mark, for word-counted waits and for the strobes between a
TRNG reset release and the clean start. ``measure_period`` returns the
clocks of one strobe period, measured between two strobes that the task
counted; a leaf logs it and grades nothing on it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from sep_monitor_life import MonitorLife
from sep_monitor_life import MonitorLifeError as MonitorLifeError

from env.sep_seeded_rng import SepSeededRng

NUM_LANES = 12
PERIOD = 64
BIAS70_ONES = 45
BIAS30_ONES = 19
SQUARE_LENGTHS = (8, 16, 32)
# 6-bit masks of odd weight: 32 values.
ODD_MASKS = tuple(m for m in range(1, PERIOD) if bin(m).count("1") % 2 == 1)


class EsrcStrobeTimeout(AssertionError):
    """A strobe wait expired: ``missing`` of ``count`` strobes did not come in ``bound`` clocks."""

    def __init__(self, count: int, missing: int, bound: int) -> None:
        super().__init__(
            f"ESRC-PATTERN-NOISE: {missing} of {count} strobes missing after {bound} clocks"
        )
        self.count = count
        self.missing = missing
        self.bound = bound


class EsrcNoiseXZError(AssertionError):
    """The strobe or a lane byte resolved to X or Z."""


class LanePattern:
    """The bit a lane carries at word ``n``."""

    def bit(self, n: int) -> int:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class Stuck(LanePattern):
    value: int

    def bit(self, n: int) -> int:
        return self.value & 1

    def describe(self) -> str:
        return f"stuck{self.value & 1}"


@dataclass(frozen=True)
class Balanced(LanePattern):
    mask: int
    perm: tuple[int, ...]

    def bit(self, n: int) -> int:
        return bin(self.mask & self.perm[n % PERIOD]).count("1") & 1

    def describe(self) -> str:
        return f"balanced(m=0x{self.mask:02x})"


@dataclass(frozen=True)
class Ones(LanePattern):
    name: str
    positions: frozenset[int]

    def bit(self, n: int) -> int:
        return 1 if (n % PERIOD) in self.positions else 0

    def describe(self) -> str:
        return f"{self.name}(ones={sorted(self.positions)})"


@dataclass(frozen=True)
class Square(LanePattern):
    length: int
    phase: int

    def bit(self, n: int) -> int:
        return ((n + self.phase) // self.length) & 1

    def describe(self) -> str:
        return f"square{self.length}(phase={self.phase})"


@dataclass(frozen=True)
class Alternate(LanePattern):
    start: int

    def bit(self, n: int) -> int:
        return (self.start ^ n) & 1

    def describe(self) -> str:
        return f"alternate(start={self.start & 1})"


def balanced_lanes(rng: SepSeededRng, lanes: int = NUM_LANES) -> list[Balanced]:
    """``lanes`` balanced patterns: different odd-weight masks, one shared permutation."""
    if not 1 <= lanes <= len(ODD_MASKS):
        raise ValueError(f"lanes must be 1 to {len(ODD_MASKS)}")
    masks = rng.sample(ODD_MASKS, lanes)
    perm = list(range(PERIOD))
    rng.shuffle(perm)
    p = tuple(perm)
    return [Balanced(m, p) for m in masks]


def bias_lane(rng: SepSeededRng, ones: int) -> Ones:
    """``bias70`` (45 ones) or ``bias30`` (19 ones) at drawn word positions."""
    if ones not in (BIAS70_ONES, BIAS30_ONES):
        raise ValueError(f"ones must be {BIAS70_ONES} (bias70) or {BIAS30_ONES} (bias30)")
    name = "bias70" if ones == BIAS70_ONES else "bias30"
    return Ones(name, frozenset(rng.sample(range(PERIOD), ones)))


def square_lane(rng: SepSeededRng, length: int) -> Square:
    """Runs of exactly ``length`` (8, 16 or 32) words, with a drawn phase."""
    if length not in SQUARE_LENGTHS:
        raise ValueError(f"length must be one of {SQUARE_LENGTHS}")
    return Square(length, rng.randrange(0, 2 * length))


def alternate_lane(rng: SepSeededRng) -> Alternate:
    """A bit that changes on every word, with a drawn start value."""
    return Alternate(rng.randrange(0, 2))


def describe(patterns: Sequence[LanePattern]) -> str:
    """One plan-log text for the patterns of the 12 lanes."""
    out = [f"lane{j}={p.describe()}" for j, p in enumerate(patterns)]
    perms = {p.perm for p in patterns if isinstance(p, Balanced)}
    for perm in sorted(perms):
        out.append(f"perm={list(perm)}")
    return " ".join(out)


class SepEsrcPatternNoise:
    """Drives the exact lane patterns on ``esrc_noise_ext_i``, word by word."""

    def __init__(self, dut=None, *, logger: logging.Logger | None = None) -> None:
        self.dut: Any = dut if dut is not None else cocotb.top
        self.log = (
            logger if logger is not None else logging.getLogger("cocotb.sep_esrc_pattern_noise")
        )
        self.clk = 0
        self.word = 0
        self.strobe_clk = 0
        self.patterns: list[LanePattern] = []
        self._pending: list[LanePattern] | None = None
        self._whole = False
        self._held = 0
        self._check = False
        self.bytes_compared = 0
        self.byte_mismatches: list[tuple[int, int, int, int]] = []
        self.life = MonitorLife("ESRC-PATTERN-NOISE", lambda: self.clk)
        self._task: Any = None

    @staticmethod
    def _check_patterns(patterns: Sequence[LanePattern]) -> list[LanePattern]:
        if len(patterns) != NUM_LANES:
            raise ValueError(f"need one pattern per lane ({NUM_LANES}), got {len(patterns)}")
        return list(patterns)

    def _bits(self, n: int) -> int:
        return sum(p.bit(n) << j for j, p in enumerate(self.patterns))

    def _apply_now(self) -> None:
        self._held = self._bits(self.word)
        self.dut.esrc_noise_ext_i.value = self._held

    def start(self, patterns: Sequence[LanePattern]) -> "SepEsrcPatternNoise":
        """Apply word 0 of ``patterns`` now and start the strobe-synchronous task."""
        self.patterns = self._check_patterns(patterns)
        self.word = 0
        self._whole = False
        self._apply_now()
        self.log.info("ESRC-PATTERN-NOISE start %s", describe(self.patterns))
        if self._task is None:
            self._task = self.life.start(self._run())
        return self

    async def stop(self) -> None:
        """Stop the task; the lanes keep their last bits."""
        self._task = None
        await self.life.stop()

    def set_lanes(self, patterns: Sequence[LanePattern], *, immediate: bool = False) -> None:
        """Change the patterns of all lanes.

        By default the change takes effect at the next strobe, so every word stays
        whole. ``immediate`` applies the bits of the current word now; use it only
        while the generators make no strobe (``CTRL.MODULE_ENABLE`` = 0), because
        the current word is then not whole.
        """
        new = self._check_patterns(patterns)
        if immediate:
            self.patterns = new
            self._pending = None
            self._whole = False
            self._apply_now()
            self.log.info("ESRC-PATTERN-NOISE set now word=%d %s", self.word, describe(new))
        else:
            self._pending = new
            self.log.info("ESRC-PATTERN-NOISE set at next strobe %s", describe(new))

    def byte_check(self, enabled: bool) -> None:
        """Turn the lane-byte control on or off (on only while BYPASS is set on all lanes)."""
        self._check = enabled

    def byte_control(self) -> tuple[int, int]:
        """(bytes compared, mismatches) since the start of the driver."""
        self.life.check()
        return self.bytes_compared, len(self.byte_mismatches)

    @property
    def running(self) -> bool:
        """True while the strobe-synchronous task runs."""
        return self._task is not None

    def held_bits(self) -> int:
        """The 12 lane bits of the current word."""
        return self._held

    def mark(self) -> int:
        """The current word index (the strobes counted since ``start``)."""
        return self.word

    def words_since(self, mark: int) -> int:
        """The strobes counted after ``mark``."""
        return self.word - mark

    async def measure_period(self, n: int = 8, *, bound: int) -> int:
        """Clocks of one strobe period: the clocks from a strobe to the ``n``-th strobe after it, / ``n``.

        Both strobes are clocks that the task counted, so the span is exact. Raises
        if the span is not a whole multiple of ``n`` or a strobe is missing after
        ``bound`` clocks.
        """
        if n <= 0:
            raise ValueError("n must be positive")
        await self.wait_words(1, bound)
        first = self.strobe_clk
        await self.wait_words(n, bound)
        span = self.strobe_clk - first
        if span % n:
            raise AssertionError(
                f"ESRC-PATTERN-NOISE: {n} strobe periods span {span} clocks, not a whole period"
            )
        return span // n

    async def wait_words(self, count: int, bound: int) -> int:
        """Wait for ``count`` more strobes, at most ``bound`` clocks; return the word index."""
        target = self.word + count
        for _ in range(bound + 1):
            if self.word >= target:
                return self.word
            self.life.require_running()
            await RisingEdge(self.dut.clk_i)
        raise EsrcStrobeTimeout(count, target - self.word, bound)

    @staticmethod
    def _bitstr(sig) -> str:
        v = sig.value
        s = getattr(v, "binstr", None)
        return (s if s is not None else str(v)).strip()

    def _xz(self, what: str) -> None:
        msg = f"ESRC-NOISE-XZ FAIL: {what} clk={self.clk}"
        self.log.error(msg)
        raise EsrcNoiseXZError(msg)

    def _compare_bytes(self) -> None:
        raw = self._bitstr(self.dut.esrc_decor_bytes_o)
        width = len(raw)
        for j in range(NUM_LANES):
            byte = raw[width - 8 * (j + 1) : width - 8 * j]
            if any(c not in "01" for c in byte):
                self._xz(f"esrc_decor_bytes_o lane {j} = {byte}")
            got = int(byte, 2)
            want = 0xFF if (self._held >> j) & 1 else 0x00
            self.bytes_compared += 1
            if got != want:
                self.byte_mismatches.append((self.word, j, want, got))

    async def _run(self) -> None:
        d = self.dut
        clk = d.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            v = self._bitstr(d.esrc_decor_valid_o)
            if v not in "01":
                self._xz(f"esrc_decor_valid_o = {v}")
            if v != "1":
                continue
            if self._check and self._whole:
                self._compare_bytes()
            self.word += 1
            self.strobe_clk = self.clk
            if self._pending is not None:
                self.patterns = self._pending
                self._pending = None
            self._whole = True
            self._held = self._bits(self.word)
            await NextTimeStep()
            d.esrc_noise_ext_i.value = self._held
