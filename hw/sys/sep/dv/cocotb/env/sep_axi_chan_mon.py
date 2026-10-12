# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Channel monitor and response-ready hold for the testbench AXI masters.

Two parts, both on the flat master ports of tb_top (``s_axi_*``, the CPU-LSU
master; ``m_axi_*``, the SMN-inbound external master):

* :class:`SepAxiChanMon` reads the five channels on every rising edge of
  ``clk_i``, in the read-only phase, and drives nothing. It records each
  handshake (VALID and READY high on one edge) with its clock index, ID and,
  for B and R, the response code and RLAST. It also counts, per response
  channel, the clocks on which VALID is high and READY is low, so a leaf can
  show that a held response was presented and not taken. A VALID or READY
  that resolves to X or Z fails the leaf with ``CHAN-XZ FAIL`` while
  ``xz_fail`` is set. An ID, response code or RLAST that resolves to X or Z
  on a handshake is recorded as :data:`XZ` (never as None), which compares
  unequal to every code, and fails the leaf with ``CHAN-XZ FAIL`` while
  ``xz_fail`` is set; :meth:`SepAxiChanMon.xz_beats` lists such beats for a
  caller that grades them. Verilator is 2-state.
* :class:`SepAxiReadyHold` holds BREADY or RREADY of one master low through
  the backend channel ``pause`` that ``ocah_axi_vip`` exposes
  (``OcahAxiMasterDriver.channels``), and releases it. The VIP keeps the
  transaction outstanding while the channel is paused, so the access completes
  with its own response after the release.

The ``wait_*`` methods return in the read-only phase of a clock; a caller
awaits the next edge before it drives a signal.

A no_cpu leaf that holds the CPU-LSU master must first stop the background
entropy-FIFO drain that shares that master (``sep_base_test.stop_fifo_drain``).

Usage::

    mon = SepAxiChanMon("s_axi").start()
    hold = SepAxiReadyHold(test, "s_axi")
    hold.hold("r")
    m = mon.mark()
    ...issue the read; wait until mon.valid_waiting("r") ...
    assert mon.count(m, "r") == 0
    hold.release("r")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

CHANNELS = ("aw", "w", "ar", "b", "r")
_RESP_CH = ("b", "r")
_CHAN_KEY = {"b": "b_ready_delay", "r": "r_ready_delay"}


class ChanXZError(AssertionError):
    """A handshake signal of the watched master resolved to X or Z."""


class _Xz:
    """The value of a beat field that resolved to X or Z."""

    def __repr__(self) -> str:
        return "X"


XZ = _Xz()


@dataclass(frozen=True)
class ChanBeat:
    """One handshake: clock index, channel, ID, response code and RLAST.

    A field is None where the channel has no such signal (no ID port, ``last``
    on B, ``resp`` on a request channel), and :data:`XZ` where it resolved to X
    or Z.
    """

    clk: int
    ch: str
    axi_id: int | _Xz | None
    resp: int | _Xz | None = None
    last: int | _Xz | None = None

    @property
    def has_xz(self) -> bool:
        return XZ in (self.axi_id, self.resp, self.last)


def _val(sig) -> int | None:
    v = sig.value
    return int(v) if v.is_resolvable else None


def _field(sig) -> int | _Xz:
    v = sig.value
    return int(v) if v.is_resolvable else XZ


class SepAxiChanMon:
    """Per-clock monitor of the AW, W, AR, B and R channels of one master."""

    def __init__(self, prefix: str, dut=None, *, xz_fail: bool = True) -> None:
        if prefix not in ("s_axi", "m_axi"):
            raise ValueError(f"prefix must be 's_axi' or 'm_axi', got {prefix!r}")
        self.dut: Any = dut if dut is not None else cocotb.top
        self.prefix = prefix
        self.xz_fail = xz_fail
        self.beats: list[ChanBeat] = []
        self.clk = 0
        self.waiting = {ch: 0 for ch in _RESP_CH}
        self._waiting_now = {ch: False for ch in _RESP_CH}
        self._task: Any = None
        self._sig = {
            ch: (
                getattr(self.dut, f"{prefix}_{ch}valid"),
                getattr(self.dut, f"{prefix}_{ch}ready"),
                getattr(self.dut, f"{prefix}_{ch}id", None),
            )
            for ch in CHANNELS
        }
        self._resp = {ch: getattr(self.dut, f"{prefix}_{ch}resp") for ch in _RESP_CH}
        self._rlast = getattr(self.dut, f"{prefix}_rlast")

    def start(self) -> "SepAxiChanMon":
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None

    def mark(self) -> int:
        """Index of the next recorded handshake."""
        return len(self.beats)

    def since(self, mark: int, ch: str | None = None) -> list[ChanBeat]:
        return [b for b in self.beats[mark:] if ch is None or b.ch == ch]

    def count(self, mark: int, ch: str) -> int:
        return len(self.since(mark, ch))

    def xz_beats(self, mark: int, ch: str | None = None) -> list[ChanBeat]:
        """Handshakes after ``mark`` with an ID, response code or RLAST at X or Z."""
        return [b for b in self.since(mark, ch) if b.has_xz]

    def waiting_clocks(self, ch: str) -> int:
        """Total clocks so far with VALID high and READY low on ``ch`` (b or r)."""
        return self.waiting[ch]

    def valid_waiting(self, ch: str) -> bool:
        """True on the last sampled clock if ``ch`` VALID is high and READY low."""
        return self._waiting_now[ch]

    async def wait_valid_waiting(self, ch: str, bound: int) -> int:
        """Wait up to ``bound`` clocks for VALID high with READY low on ``ch``.

        Returns the clock index. Raises AssertionError on timeout.
        """
        start = self.clk
        while not self._waiting_now[ch]:
            if self.clk - start >= bound:
                raise AssertionError(
                    f"{self.prefix} {ch}: no VALID with READY low within {bound} clocks"
                )
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
        return self.clk

    async def wait_beat(self, mark: int, ch: str, bound: int) -> ChanBeat:
        """Wait up to ``bound`` clocks for a ``ch`` handshake after ``mark``."""
        start = self.clk
        while not self.since(mark, ch):
            if self.clk - start >= bound:
                raise AssertionError(f"{self.prefix} {ch}: no handshake within {bound} clocks")
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
        return self.since(mark, ch)[0]

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            for ch in CHANNELS:
                vs, rs, ids = self._sig[ch]
                v, r = _val(vs), _val(rs)
                if v is None or r is None:
                    if self.xz_fail:
                        raise ChanXZError(
                            f"CHAN-XZ FAIL: {self.prefix}_{ch}valid={vs.value} "
                            f"{self.prefix}_{ch}ready={rs.value} at clock {self.clk}"
                        )
                    continue
                if ch in _RESP_CH:
                    w = bool(v and not r)
                    self._waiting_now[ch] = w
                    if w:
                        self.waiting[ch] += 1
                if v and r:
                    axi_id = _field(ids) if ids is not None else None
                    if ch in _RESP_CH:
                        last = _field(self._rlast) if ch == "r" else None
                        beat = ChanBeat(self.clk, ch, axi_id, _field(self._resp[ch]), last)
                    else:
                        beat = ChanBeat(self.clk, ch, axi_id)
                    self.beats.append(beat)
                    if beat.has_xz and self.xz_fail:
                        raise ChanXZError(
                            f"CHAN-XZ FAIL: {self.prefix} {ch} handshake id={beat.axi_id!r} "
                            f"resp={beat.resp!r} last={beat.last!r} at clock {self.clk}"
                        )


class SepAxiReadyHold:
    """Hold BREADY or RREADY of one testbench master low, and release it."""

    def __init__(self, test, prefix: str) -> None:
        if prefix == "s_axi":
            agent = test.env.axi_agent
        elif prefix == "m_axi":
            agent = test.env.ext_axi_agent
        else:
            raise ValueError(f"prefix must be 's_axi' or 'm_axi', got {prefix!r}")
        self.prefix = prefix
        self.log = test.logger
        self._drv = agent.driver.axi.driver
        self.held: set[str] = set()

    def _chan(self, ch: str):
        if ch not in _CHAN_KEY:
            raise ValueError(f"only the response channels b and r can be held, got {ch!r}")
        return self._drv.channels[_CHAN_KEY[ch]]

    def hold(self, ch: str) -> None:
        """Drive ``<prefix>_<ch>ready`` low from the next clock on."""
        chan = self._chan(ch)
        chan.clear_pause_generator()
        chan.pause = True
        self.held.add(ch)
        self.log.info("AXI-HOLD %s %sready held low", self.prefix, ch)

    def release(self, ch: str) -> None:
        chan = self._chan(ch)
        chan.pause = False
        self.held.discard(ch)
        self.log.info("AXI-HOLD %s %sready released", self.prefix, ch)

    def release_all(self) -> None:
        for ch in list(self.held):
            self.release(ch)


__all__ = ["CHANNELS", "XZ", "ChanBeat", "ChanXZError", "SepAxiChanMon", "SepAxiReadyHold"]
