# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Driver and response monitor of the three external TRNG streams of ``sep``.

The integration wrapper ties the ``sep`` inputs ``ext_trng_axis_req_i[2:0]``
and ``ext_trng_irq_i`` to zero. ``tb_top`` forces them from TB pins (top-port
drives, docs/SEP_TB_ARCH.adoc, HDL Top port table, "External TRNG streams" and
"External TRNG interrupt"):

* ``ext_trng_drive_en_i[i]``: stream i takes the pins below while 1;
* ``ext_trng_tvalid_i[i]``, ``ext_trng_tdata_i[32*i +: 32]``,
  ``ext_trng_tstrb_i[4*i +: 4]``: the beat of stream i;
* ``ext_trng_irq_drive_i``: the external TRNG interrupt (PIC source 17).

The monitor reads the read-only taps ``ext_trng_tvalid_o``, ``ext_trng_tdata_o``,
``ext_trng_tstrb_o`` (stream i as the ``sep`` port sees it) and
``ext_trng_tready_o`` (``ext_trng_axis_rsp_o[i].tready``).

Timing. ``tb_top`` re-issues the force on each falling edge of ``clk_i``. This
class writes the pins only just after a rising edge, so the port changes at the
next falling edge and holds through the next rising edge. In the read-only
phase after each falling edge the monitor samples the taps: a stream with
tvalid and tready high there transfers its beat on the next rising edge. tready
is a function of DUT state that changes on rising edges, so the sample is the
value that rising edge sees. Clock ``n`` is the n-th sample after ``start``.

AXI-Stream source rule. A beat stays on the port, unchanged, from the first
clock it shows tvalid to the clock it transfers. The one exception is
``source_reset``, a reset of the external source: it drops the held beat and
the queue of the stream on the next rising edge, and logs ``EXT-SRC-RESET``.

Each sample also compares the port with the beat that the driver holds. A
difference (the force did not reach the port) fails the leaf with
``EXT-TRNG-DRIVE FAIL``. A tvalid or tready bit of a driven stream that
resolves to X or Z fails it with ``EXT-TRNG-XZ FAIL``. A query after the task
ended without ``stop`` raises ``MonitorLifeError``.

Gaps. With ``gap_rng`` set, the driver holds tvalid low for a drawn number of
clocks (0 to ``max_gap``) after each transfer, before the next beat of the
stream; the draws are a pure function of the generator state.

Usage::

    ext = SepExtTrngStream(gap_rng=rng, max_gap=3).start(streams=(0,))
    m = ext.mark()
    ext.send(0, words)
    await ext.wait_sent(0, bound=20_000)
    beats = ext.beats_since(m, 0)          # [ExtTrngBeat(clk, data, strb, wait), ...]
    await ext.source_reset(0)              # at the TRNG reset, logged
    await ext.stop()
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from sep_monitor_life import MonitorLife
from sep_monitor_life import MonitorLifeError as MonitorLifeError

from env.sep_seeded_rng import SepSeededRng

NUM_STREAMS = 3
WORD_BITS = 32
STRB_BITS = 4
STRB_ALL = (1 << STRB_BITS) - 1


class ExtTrngDriveError(AssertionError):
    """The port did not carry the beat that the driver holds, or a handshake bit was X/Z."""


class ExtTrngTimeout(AssertionError):
    """A bounded wait on a stream expired."""


@dataclass(frozen=True)
class ExtTrngBeat:
    """One transfer: the clock of its sample, the word, the strobe, and the clocks it
    waited with tvalid high and tready low."""

    clk: int
    data: int
    strb: int
    wait: int


@dataclass(frozen=True)
class ExtTrngMark:
    """A point in the record: the clock, the beat count per stream and the run epoch."""

    clk: int
    n: tuple[int, ...]
    epoch: int


@dataclass
class _Stream:
    queue: deque[tuple[int, int]]
    held: tuple[int, int] | None = None
    gap: int = 0
    wait: int = 0
    reset_req: bool = False
    dropped: int = 0


class SepExtTrngStream:
    """Drives the external TRNG streams and records each transfer."""

    def __init__(
        self,
        dut=None,
        *,
        gap_rng: SepSeededRng | None = None,
        max_gap: int = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        if max_gap < 0:
            raise ValueError("max_gap must be 0 or more")
        if max_gap and gap_rng is None:
            raise ValueError("max_gap needs gap_rng: gaps are drawn from the seeded generator")
        self.dut: Any = dut if dut is not None else cocotb.top
        self.gap_rng = gap_rng
        self.max_gap = max_gap
        self.log = logger if logger is not None else logging.getLogger("cocotb.sep_ext_trng_stream")
        self.clk = 0
        self.enabled: tuple[int, ...] = ()
        self._s = [_Stream(deque()) for _ in range(NUM_STREAMS)]
        self._beats: list[list[ExtTrngBeat]] = [[] for _ in range(NUM_STREAMS)]
        self.life = MonitorLife("EXT-TRNG-STREAM", lambda: self.clk)
        self._task: Any = None

    # ------------------------------------------------------------------ control
    def start(self, streams: Iterable[int] = range(NUM_STREAMS)) -> "SepExtTrngStream":
        """Take the pins of ``streams`` (idle beats) and start the driver task."""
        en = tuple(sorted(set(streams)))
        for i in en:
            self._check_stream(i)
        d = self.dut
        d.ext_trng_tvalid_i.value = 0
        d.ext_trng_tdata_i.value = 0
        d.ext_trng_tstrb_i.value = 0
        d.ext_trng_drive_en_i.value = sum(1 << i for i in en)
        self.enabled = en
        self.log.info("EXT-TRNG-STREAM start streams=%s max_gap=%d", list(en), self.max_gap)
        if self._task is None:
            self._task = self.life.start(self._run())
        return self

    async def stop(self, *, release: bool = True) -> None:
        """Stop the task, drop tvalid and every held or queued beat and, with
        ``release``, give the streams back to the wrapper tie-off. Raises
        ``MonitorLifeError`` if the task ended before."""
        self._task = None
        await self.life.stop()
        for s in self._s:
            s.queue.clear()
            s.held = None
            s.gap = 0
            s.wait = 0
            s.reset_req = False
        d = self.dut
        d.ext_trng_tvalid_i.value = 0
        if release:
            d.ext_trng_drive_en_i.value = 0
            self.enabled = ()

    def set_irq(self, level: int) -> None:
        """Drive the external TRNG interrupt (``ext_trng_irq_drive_i``) to ``level``."""
        self.dut.ext_trng_irq_drive_i.value = 1 if level else 0
        self.log.info("EXT-TRNG-IRQ drive=%d", 1 if level else 0)

    def send(self, stream: int, words: Iterable[int], strb: int = STRB_ALL) -> None:
        """Queue ``words`` on ``stream``; each beat carries ``strb``."""
        self._check_stream(stream)
        if stream not in self.enabled:
            raise ValueError(f"stream {stream} is not driven (start(streams=...))")
        if not 0 <= strb <= STRB_ALL:
            raise ValueError(f"strb 0x{strb:x} is wider than {STRB_BITS} bits")
        q = self._s[stream].queue
        for w in words:
            if not 0 <= w < (1 << WORD_BITS):
                raise ValueError(f"word 0x{w:x} is wider than {WORD_BITS} bits")
            q.append((w, strb))

    def pending(self, stream: int) -> int:
        """Beats of ``stream`` not yet transferred (the held beat and the queue)."""
        self.life.check()
        s = self._s[stream]
        return len(s.queue) + (1 if s.held is not None else 0)

    async def source_reset(self, stream: int) -> int:
        """Reset the source of ``stream``: on the next rising edge drop its held beat
        and its queue. Returns the number of beats dropped; logs ``EXT-SRC-RESET``."""
        self._check_stream(stream)
        self.life.require_running()
        s = self._s[stream]
        s.reset_req = True
        while s.reset_req:
            self.life.require_running()
            await RisingEdge(self.dut.clk_i)
        return s.dropped

    async def wait_sent(self, stream: int, bound: int) -> int:
        """Wait at most ``bound`` clocks until ``stream`` has no pending beat; return the clock."""
        for _ in range(bound + 1):
            if self.pending(stream) == 0:
                return self.clk
            self.life.require_running()
            await RisingEdge(self.dut.clk_i)
        raise ExtTrngTimeout(
            f"EXT-TRNG stream {stream}: {self.pending(stream)} beats still pending after "
            f"{bound} clocks"
        )

    # ------------------------------------------------------------------ record
    def mark(self) -> ExtTrngMark:
        return ExtTrngMark(self.clk, tuple(len(b) for b in self._beats), self.life.mark_epoch())

    def beats_since(self, mark: ExtTrngMark, stream: int) -> list[ExtTrngBeat]:
        """Transfers of ``stream`` after ``mark``, in order."""
        self.life.check(mark.epoch)
        if self.clk <= mark.clk:
            raise MonitorLifeError(
                f"EXT-TRNG-STREAM took no sample after the mark (clk={self.clk} "
                f"mark_clk={mark.clk})"
            )
        return list(self._beats[stream][mark.n[stream] :])

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _check_stream(i: int) -> None:
        if not 0 <= i < NUM_STREAMS:
            raise ValueError(f"stream {i} is not 0 to {NUM_STREAMS - 1}")

    @staticmethod
    def _bits(sig) -> str:
        v = sig.value
        s = getattr(v, "binstr", None)
        return (s if s is not None else str(v)).strip()

    def _fail(self, msg: str) -> None:
        self.log.error(msg)
        raise ExtTrngDriveError(msg)

    def _draw_gap(self) -> int:
        if self.gap_rng is None or self.max_gap == 0:
            return 0
        return int(self.gap_rng.randrange(0, self.max_gap + 1))

    def _drive_pins(self) -> None:
        tvalid = tdata = tstrb = 0
        for i in self.enabled:
            held = self._s[i].held
            if held is not None:
                tvalid |= 1 << i
                tdata |= held[0] << (WORD_BITS * i)
                tstrb |= held[1] << (STRB_BITS * i)
        d = self.dut
        d.ext_trng_tvalid_i.value = tvalid
        d.ext_trng_tdata_i.value = tdata
        d.ext_trng_tstrb_i.value = tstrb

    async def _run(self) -> None:
        d = self.dut
        clk = d.clk_i
        while True:
            await FallingEdge(clk)
            await ReadOnly()
            self.clk += 1
            valid = self._bits(d.ext_trng_tvalid_o)
            ready = self._bits(d.ext_trng_tready_o)
            data = self._bits(d.ext_trng_tdata_o)
            strb = self._bits(d.ext_trng_tstrb_o)
            xfer = [False] * NUM_STREAMS
            for i in self.enabled:
                v = valid[len(valid) - 1 - i]
                r = ready[len(ready) - 1 - i]
                if v not in "01" or r not in "01":
                    self._fail(f"EXT-TRNG-XZ FAIL: stream {i} tvalid={v} tready={r} clk={self.clk}")
                s = self._s[i]
                if s.held is None:
                    if v != "0":
                        self._fail(
                            f"EXT-TRNG-DRIVE FAIL: stream {i} shows tvalid=1 with no held beat "
                            f"clk={self.clk}"
                        )
                    continue
                lo = len(data) - WORD_BITS * (i + 1)
                w = data[lo : lo + WORD_BITS]
                slo = len(strb) - STRB_BITS * (i + 1)
                sb = strb[slo : slo + STRB_BITS]
                port_word = int(w, 2) if all(c in "01" for c in w) else None
                port_strb = int(sb, 2) if all(c in "01" for c in sb) else None
                if v != "1" or port_word != s.held[0] or port_strb != s.held[1]:
                    self._fail(
                        f"EXT-TRNG-DRIVE FAIL: stream {i} port tvalid={v} tdata={w} tstrb={sb}; "
                        f"held 0x{s.held[0]:08x}/0x{s.held[1]:x} clk={self.clk}"
                    )
                if r == "1":
                    self._beats[i].append(ExtTrngBeat(self.clk, s.held[0], s.held[1], s.wait))
                    xfer[i] = True
                else:
                    s.wait += 1
            await RisingEdge(clk)
            for i in self.enabled:
                s = self._s[i]
                if s.reset_req:
                    s.dropped = len(s.queue) + (0 if xfer[i] or s.held is None else 1)
                    s.queue.clear()
                    s.held = None
                    s.gap = 0
                    s.wait = 0
                    s.reset_req = False
                    self.log.info(
                        "EXT-SRC-RESET stream=%d dropped_beats=%d clk=%d", i, s.dropped, self.clk
                    )
                    continue
                if xfer[i]:
                    s.held = None
                    s.wait = 0
                    s.gap = self._draw_gap()
                if s.held is None and s.queue:
                    if s.gap > 0:
                        s.gap -= 1
                    else:
                        s.held = s.queue.popleft()
            self._drive_pins()
