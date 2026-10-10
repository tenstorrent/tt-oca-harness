# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Monitor of the secure DMA master and status taps of tb_top.

``dma_axi_req_probe_o`` is a read-only copy of the DMA master request after the
DMA local-alias remap and of its response READY/VALID (bit layout in
tb/sep_tb_signal_list.svh, decoded by ``FIELDS`` below). ``dma_status_probe_o``
carries the stored level of each DMA STATUS bit, bit i for STATUS bit i.
Both are in the observation-probe list of docs/SEP_TB_ARCH.adoc.

On every rising edge of ``clk_i``, in the read-only phase, the monitor records:

* each AR and AW handshake (VALID and READY high): clock, address, AxLEN and
  AxSIZE;
* each W handshake: clock, WSTRB and WLAST;
* each B handshake: clock and BRESP;
* each level change of DONE, CHUNK_DONE, ERROR, ABORTED, SHA2_DIGEST_VALID and
  BUSY: clock, name and new level.

Clock ``n`` is the n-th sampled edge after ``start``. A VALID or READY bit, or
a STATUS bit, that resolves to X or Z fails the leaf with ``DMA-TAP-XZ FAIL``,
so a check that counts no beat cannot pass on an unknown handshake. Verilator
is 2-state.

Usage::

    tap = SepDmaTap().start()
    m = tap.mark()
    ...GO and wait for DONE...
    ev = tap.since(m)
    [b.addr for b in ev.ar], [b.strb for b in ev.w], ev.status_edges
    await tap.stop()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from sep_reg_meta import RegBlock

# (name, lsb, width) of dma_axi_req_probe_o; tb/sep_tb_signal_list.svh states the same layout.
FIELDS: tuple[tuple[str, int, int], ...] = (
    ("ar_valid", 0, 1),
    ("ar_ready", 1, 1),
    ("ar_addr", 2, 32),
    ("ar_len", 34, 8),
    ("ar_size", 42, 3),
    ("aw_valid", 45, 1),
    ("aw_ready", 46, 1),
    ("aw_addr", 47, 32),
    ("aw_len", 79, 8),
    ("aw_size", 87, 3),
    ("w_valid", 90, 1),
    ("w_ready", 91, 1),
    ("w_strb", 92, 8),
    ("w_last", 100, 1),
    ("b_valid", 101, 1),
    ("b_ready", 102, 1),
    ("b_resp", 103, 2),
)
PROBE_WIDTH = 105
_F = {n: (lsb, w) for n, lsb, w in FIELDS}
_HANDSHAKE_BITS = tuple(
    _F[n][0]
    for n in (
        "ar_valid",
        "ar_ready",
        "aw_valid",
        "aw_ready",
        "w_valid",
        "w_ready",
        "b_valid",
        "b_ready",
    )
)

_DMA = RegBlock("SECURE_DMA")
# STATUS bit positions from the generated register metadata.
STATUS_BITS: dict[str, int] = {
    name: _DMA.field_lsb("STATUS", name)
    for name in ("busy", "done", "aborted", "error", "sha2_digest_valid", "chunk_done")
}


class DmaTapXZError(AssertionError):
    """A DMA tap handshake or status bit resolved to X or Z."""


@dataclass(frozen=True)
class DmaBeat:
    """One handshake on one channel of the DMA master."""

    ch: str
    clk: int
    addr: int | None = None
    len: int | None = None
    size: int | None = None
    strb: int | None = None
    last: int | None = None
    resp: int | None = None


@dataclass
class DmaTapEvents:
    """The records of one window of the tap."""

    ar: list[DmaBeat] = field(default_factory=list)
    aw: list[DmaBeat] = field(default_factory=list)
    w: list[DmaBeat] = field(default_factory=list)
    b: list[DmaBeat] = field(default_factory=list)
    status_edges: list[tuple[int, str, int]] = field(default_factory=list)

    def rises(self, name: str) -> list[int]:
        """Clocks at which STATUS bit ``name`` went from 0 to 1."""
        return [c for c, n, lvl in self.status_edges if n == name and lvl == 1]

    def falls(self, name: str) -> list[int]:
        return [c for c, n, lvl in self.status_edges if n == name and lvl == 0]

    def last_beat_clk(self) -> int | None:
        """Clock of the last W or B handshake in the window, or None."""
        clks = [x.clk for x in self.w + self.b]
        return max(clks) if clks else None


@dataclass(frozen=True)
class DmaTapMark:
    clk: int
    n: tuple[int, int, int, int, int]


class SepDmaTap:
    """Records the DMA master handshakes and the STATUS level changes until stopped."""

    def __init__(self, dut=None, *, xz_fail: bool = True) -> None:
        self.dut: Any = dut if dut is not None else cocotb.top
        self.xz_fail = xz_fail
        dut_any: Any = self.dut
        self._req = dut_any.dma_axi_req_probe_o
        self._st = dut_any.dma_status_probe_o
        self.clk = 0
        self.ev = DmaTapEvents()
        self.status: dict[str, int] = {}
        self._task: Any = None
        self.log = logging.getLogger("cocotb.sep_dma_tap")

    def start(self) -> "SepDmaTap":
        width = len(self._req)
        if width != PROBE_WIDTH:
            raise AssertionError(
                f"dma_axi_req_probe_o is {width} bits; the decoder expects {PROBE_WIDTH}"
            )
        if self._task is None:
            self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def mark(self) -> DmaTapMark:
        e = self.ev
        return DmaTapMark(self.clk, (len(e.ar), len(e.aw), len(e.w), len(e.b), len(e.status_edges)))

    def since(self, mark: DmaTapMark) -> DmaTapEvents:
        """The records after ``mark``."""
        e = self.ev
        a, aw, w, b, s = mark.n
        return DmaTapEvents(e.ar[a:], e.aw[aw:], e.w[w:], e.b[b:], e.status_edges[s:])

    def between(self, m0: DmaTapMark, m1: DmaTapMark) -> DmaTapEvents:
        """The records after ``m0`` and up to ``m1``."""
        e = self.ev
        (a0, aw0, w0, b0, s0), (a1, aw1, w1, b1, s1) = m0.n, m1.n
        return DmaTapEvents(
            e.ar[a0:a1], e.aw[aw0:aw1], e.w[w0:w1], e.b[b0:b1], e.status_edges[s0:s1]
        )

    def level(self, name: str) -> int | None:
        """The STATUS bit ``name`` at the last sample."""
        return self.status.get(name)

    @staticmethod
    def _bits(sig) -> str:
        v = sig.value
        s = getattr(v, "binstr", None)
        return (s if s is not None else str(v)).strip()

    def _xz(self, what: str) -> None:
        msg = f"DMA-TAP-XZ FAIL: {what} clk={self.clk}"
        self.log.error(msg)
        raise DmaTapXZError(msg)

    async def _run(self) -> None:
        clk = self.dut.clk_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.clk += 1
            now = self.clk
            req = self._bits(self._req)
            n = len(req)

            def bit(lsb: int) -> str:
                return req[n - 1 - lsb]

            bad = [b for b in _HANDSHAKE_BITS if bit(b) not in "01"]
            if bad and self.xz_fail:
                self._xz(f"dma_axi_req_probe_o handshake bits {bad} = {req}")

            def fld(name: str) -> int | None:
                lsb, w = _F[name]
                s = req[n - lsb - w : n - lsb]
                return int(s, 2) if all(c in "01" for c in s) else None

            def hs(ch: str) -> bool:
                return bit(_F[f"{ch}_valid"][0]) == "1" and bit(_F[f"{ch}_ready"][0]) == "1"

            if hs("ar"):
                self.ev.ar.append(
                    DmaBeat("ar", now, addr=fld("ar_addr"), len=fld("ar_len"), size=fld("ar_size"))
                )
            if hs("aw"):
                self.ev.aw.append(
                    DmaBeat("aw", now, addr=fld("aw_addr"), len=fld("aw_len"), size=fld("aw_size"))
                )
            if hs("w"):
                self.ev.w.append(DmaBeat("w", now, strb=fld("w_strb"), last=fld("w_last")))
            if hs("b"):
                self.ev.b.append(DmaBeat("b", now, resp=fld("b_resp")))
            st = self._bits(self._st)
            m = len(st)
            for name, idx in STATUS_BITS.items():
                c = st[m - 1 - idx]
                if c not in "01":
                    if self.xz_fail:
                        self._xz(f"dma_status_probe_o[{idx}] ({name}) = {c}")
                    continue
                lvl = int(c)
                prev = self.status.get(name)
                if prev is not None and prev != lvl:
                    self.ev.status_edges.append((now, name, lvl))
                self.status[name] = lvl
