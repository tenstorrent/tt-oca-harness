# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""32-bit word records that test-generated code stores to the outbound mailbox.

Generated code (``env/sep_rv32_asm``) logs values with 32-bit stores to
offsets of the outbound mailbox base (``tb/sep_outbound_mbx.sv``). The stores
leave SEP on the outbound port, where the PR-OUT tap (``env/sep_fabric_tap``)
records the AW and W handshakes. :class:`SepMbxWords` pairs each AW with its
single W beat in order and decodes one record per store: the byte offset from
the mailbox base and the 32-bit value of the lane that the strobe selects.

A write that is not one beat, or a strobe that is not one full 32-bit lane,
fails the leaf: the record shape is part of the generated code, so another
shape shows a broken path and is never dropped.

``records``, ``since`` and ``find`` apply the idle-tap guard of the PR-OUT tap:
they raise ``TapIdleError`` when the tap took no sample after the mark (a mark
from :meth:`SepMbxWords.mark`; with no mark, when the tap never sampled), so an
absence or a count cannot pass on a tap that was not started or was stopped
before the stimulus. They raise ``MonitorLifeError`` when the tap task ended
without ``stop``, or when the mark is from an earlier run of the tap.

After the tap is stopped, its record is final: an AW without its W, or a W
without its AW, fails the query instead of being dropped.

``step`` returns after the tap sampled the next ``clk_i`` edge, and raises
unless the tap is running. ``wait`` checks the record after each of its
``bound`` steps, so a store on the last edge counts, and raises when the bound
expires.

Usage::

    out = SepFabricTap("PR-OUT").start()
    mbx = SepMbxWords(out, MBX)
    rec = await mbx.wait(OFF_DONE, bound=100_000)
    vals = [r.val for r in mbx.since(mark, OFF_VAL)]
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import NextTimeStep, RisingEdge

from env.sep_fabric_tap import TapIdleError


@dataclass(frozen=True)
class MbxRec:
    seq: int
    off: int
    val: int
    t_ps: int


class MbxMark(int):
    """A record index that also carries the sampled clock count and run epoch of the tap."""

    clk: int
    epoch: int

    def __new__(cls, index: int, clk: int, epoch: int) -> "MbxMark":
        obj = super().__new__(cls, index)
        obj.clk = clk
        obj.epoch = epoch
        return obj


class SepMbxWords:
    """Decoded word records of one PR-OUT tap."""

    def __init__(self, out_tap, base: int) -> None:
        self.tap = out_tap
        self.base = base
        self._recs: list[MbxRec] = []
        self._scan = 0
        self._aws: list = []
        self._ws: list = []

    def _guard(self, after: int) -> None:
        # A plain index carries no clock count or epoch: the tap must have
        # sampled at all. A mark adds its clock count and run epoch.
        self.tap._require_sampled(after)

    def records(self) -> list[MbxRec]:
        """Every record so far; raises ``TapIdleError`` if the tap never sampled."""
        self._guard(0)
        return self._decode()

    def _decode(self) -> list[MbxRec]:
        beats = self.tap.beats
        for b in beats[self._scan :]:
            if b.ch == "aw":
                self._aws.append(b)
            elif b.ch == "w":
                self._ws.append(b)
        self._scan = len(beats)
        if self._stopped() and len(self._aws) != len(self._ws):
            raise AssertionError(
                f"MBX FAIL: stopped PR-OUT record has {len(self._aws)} AW and "
                f"{len(self._ws)} W handshakes"
            )
        while len(self._recs) < min(len(self._aws), len(self._ws)):
            i = len(self._recs)
            aw, w = self._aws[i], self._ws[i]
            if aw.addr is None or w.data is None or w.strb is None:
                raise AssertionError(f"MBX FAIL: outbound write {i} has an unknown field")
            if aw.len != 0 or not w.last:
                raise AssertionError(f"MBX FAIL: outbound write {i} is not one beat: {aw.fmt()}")
            if w.strb not in (0x0F, 0xF0):
                raise AssertionError(f"MBX FAIL: outbound write {i} strobe 0x{w.strb:x}")
            lane = 1 if w.strb == 0xF0 else 0
            off = (aw.addr & ~7) + 4 * lane - self.base
            val = (w.data >> (32 * lane)) & 0xFFFF_FFFF
            self._recs.append(MbxRec(i, off, val, w.t_ps))
        return self._recs

    def _stopped(self) -> bool:
        """True when the last run of the tap was closed by ``stop``."""
        runs = self.tap.life.runs
        return bool(runs) and runs[-1].end == "stopped"

    def mark(self) -> MbxMark:
        return MbxMark(len(self._decode()), self.tap.clk, self.tap.life.mark_epoch())

    async def step(self) -> None:
        """Return after the tap sampled the next ``clk_i`` edge; raises unless it runs."""
        self.tap.life.require_running()
        clk0 = self.tap.clk
        await RisingEdge(cocotb.top.clk_i)
        # The tap samples the edge in its ReadOnly phase; the next time step
        # follows it.
        await NextTimeStep()
        self.tap.life.require_running()
        if self.tap.clk <= clk0:
            raise TapIdleError(
                f"MBX FAIL: {self.tap.name} took no sample of the edge (clk={self.tap.clk})"
            )

    def since(self, after: int = 0, off: int | None = None) -> list[MbxRec]:
        """The records after ``after``; raises ``TapIdleError`` if the tap took no sample after it."""
        self._guard(after)
        return [r for r in self._decode()[after:] if off is None or r.off == off]

    def find(self, off: int, *, after: int = 0, val: int | None = None) -> MbxRec | None:
        """The first record at ``off`` after ``after``; raises like ``since``."""
        self._guard(after)
        for r in self._decode()[after:]:
            if r.off == off and (val is None or r.val == val):
                return r
        return None

    async def wait(
        self, off: int, bound: int, *, after: int = 0, val: int | None = None, what: str = ""
    ) -> MbxRec:
        """The first record at ``off`` (and ``val``) after ``after``, within ``bound`` clocks."""
        self.tap.life.require_running()
        self.tap.check_life(after)
        pos = after
        for n in range(bound + 1):
            recs = self._decode()
            for r in recs[pos:]:
                if r.off == off and (val is None or r.val == val):
                    return r
            pos = max(pos, len(recs))
            if n < bound:
                await self.step()
        raise AssertionError(
            f"{what or 'MBX'}: no mailbox store at +0x{off:x}"
            + ("" if val is None else f" value 0x{val:08x}")
            + f" within {bound} clk_i cycles"
        )
