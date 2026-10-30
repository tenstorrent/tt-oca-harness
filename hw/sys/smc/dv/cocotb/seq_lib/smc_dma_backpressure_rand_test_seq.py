# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Queued DMA chunks under seed-drawn hold windows on the SYS_OUT R and B responses.

Specs hw/sys/smc/doc/dma.adoc, doc/programmer/src/smc-programming.adoc (DMA Engine),
vendor idma overlay dma_ctrl.rdl.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. The hold windows drive tb_output_axi_resp_hold, which gates the
responder's R and B channels. The first window, W0, is pinned: it opens before the first launch
read and holds until every launch read has returned, then for its drawn length. Each of the one
to three drawn windows after it has a drawn chunk and opens a drawn number of clk_smc_i rises after
the first AR or R beat of that chunk following W0's release, while that chunk's read is in flight.
"""

from __future__ import annotations

import math
import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _REPO,
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    DMA_CTRL_STATUS_0,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    reg_reset_word,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import PASS_ALL_CONFIG

DESC_MIN, DESC_MAX = 5, 8
F2M_FIFO_DEPTH = 4
CHUNK_LENGTHS = (8, 40, 96, 200, 512, 1000)
# Drawn windows after the pinned first window W0.
WIN_MIN, WIN_MAX = 1, 3
# Rises from the first AR or R beat of a drawn window's chunk after W0's release to its opening.
WIN_REOPEN_MIN, WIN_REOPEN_MAX = 1, 16
WIN_LEN_MIN, WIN_LEN_MAX = 16, 4096
WINDOW = 0x0200_0000
REGION = WINDOW + 0x20_0000
CHUNK_SPAN = 0x1000
BEAT_BYTES = 8
# A pass is redrawn until every drawn window's chunk carries at least its drawn rise count plus
# two read beats.
DRAW_BOUND = 64
SRC_OFFSET = 0x10
DST_OFFSET = 0x810
GUARD = 8
GUARD_BYTE = 0xEE
POISON = 0xA5
READY_MASK = 0xFF
FUSE_SENSE_BOUND = 200_000
OPEN_WAIT_RISES = 8
# A launch read pending this long under the first window releases it.
HELD_LAUNCH_RISES = 1024
# The read and write traffic of every chunk after W0's release, beside the drawn windows' holds.
TRAFFIC_RISES = DESC_MAX * 1024
# From W0's release to the first AR or R beat of a drawn window's chunk.
ANCHOR_WAIT_RISES = TRAFFIC_RISES + WIN_MAX * (WIN_REOPEN_MAX + WIN_LEN_MAX)
# After the last launch: the rest of W0 (its drawn length), then a drawn window's anchor, opening
# rise and length.
CLOSE_WAIT_RISES = WIN_LEN_MAX + ANCHOR_WAIT_RISES + WIN_REOPEN_MAX + WIN_LEN_MAX + 16
# A launch read held by W0 up to the pending bound and W0's drawn length, then by a drawn window.
LAUNCH_BOUND_RISES = HELD_LAUNCH_RISES + WIN_LEN_MAX + WIN_REOPEN_MAX + WIN_LEN_MAX + 16
POLL_LIMIT = 3000
POLL_CYCLES = 50
ID_MASK = 0xFFFF_FFFF

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
RESET_CFG = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
RESET_START = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
RESET_END = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHECKS = (
    ("S4", "CHK-DBP-QUEUE"),
    ("S5", "CHK-DBP-BYTES"),
    ("S5", "CHK-DBP-IDS"),
    ("S5", "CHK-DBP-READY"),
)

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_output_axi_araddr",
    "tb_output_axi_bvalid",
    "tb_output_axi_bready",
    "tb_output_axi_rvalid",
    "tb_output_axi_rready",
    "tb_output_axi_read_count",
    "tb_output_axi_resp_hold",
    "tb_fuse_sense_done",
)
_SAMPLED = _TB_SIGNALS[:-1]


def _pattern(tag: int, addr: int) -> int:
    return ((addr * 13) ^ (addr >> 7) ^ (tag * 0x5B) ^ 0x3C) & 0xFF


def _next_id(prev: int) -> int:
    nxt = (prev + 1) & ID_MASK
    return nxt if nxt else 1


class _Sampler:
    """Samples at every clk_smc_i fall the values the next rise takes, with the hold pin as the
    windows drive it on that fall: every SYS_OUT AW and AR handshake (address, hold level, rise),
    every R beat with the index of its AR (bursts return in AR order, the last beat counted by
    tb_output_axi_read_count), the bursts still owed on every held rise, and the B count."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.aw: list[int] = []
        self.ar: list[tuple[int, int, int]] = []
        self.r_beats: list[tuple[int, int]] = []
        self.held: list[tuple[int, int, int]] = []
        self.read_base = -1
        self.done = 0
        self.orphan_beats = 0
        self.b = 0
        self.rises = 0

    @staticmethod
    def _bit(sig, name: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    async def run(self) -> None:
        dut = self.dut
        while True:
            await FallingEdge(dut.clk_smc_i)
            await ReadOnly()
            bit = {n: self._bit(getattr(dut, n), n) for n in _SAMPLED}
            self.rises += 1
            count = bit["tb_output_axi_read_count"]
            if self.read_base < 0:
                self.read_base = count
            self.done = count - self.read_base
            hold = bit["tb_output_axi_resp_hold"]
            if bit["tb_output_axi_awvalid"] and bit["tb_output_axi_awready"]:
                self.aw.append(bit["tb_output_axi_awaddr"])
            if bit["tb_output_axi_arvalid"] and bit["tb_output_axi_arready"]:
                self.ar.append((bit["tb_output_axi_araddr"], hold, self.rises))
            if bit["tb_output_axi_rvalid"] and bit["tb_output_axi_rready"]:
                if self.done < len(self.ar):
                    self.r_beats.append((self.done, self.rises))
                else:
                    self.orphan_beats += 1
            if hold:
                self.held.append((self.rises, self.done, len(self.ar)))
            if bit["tb_output_axi_bvalid"] and bit["tb_output_axi_bready"]:
                self.b += 1


class _Chunk:
    def __init__(self, idx: int, length: int) -> None:
        self.idx = idx
        self.name = f"C{idx}"
        self.length = length
        base = REGION + idx * CHUNK_SPAN
        self.src = base + SRC_OFFSET
        self.dst = base + DST_OFFSET
        self.payload = bytes(_pattern(idx, self.src + i) for i in range(length))
        self.id = -1
        self.status_after_launch = -1
        self.launch_rises = -1
        self.held_at_issue = False


class _Win:
    def __init__(self, idx: int, chunk: int, offset: int, length: int) -> None:
        self.idx = idx
        self.chunk = chunk
        self.offset = offset
        self.length = length
        self.opened = False
        self.closed = False
        self.open_ps = -1
        self.close_ps = -1
        self.open_rise = -1
        self.close_rise = -1
        self.outstanding = False
        self.launched = False
        self.ar_held = 0
        self.r_held = 0
        self.undelivered: list[str] = []
        self.launched_under = 0
        self.release_cause = "drawn length"
        # A drawn window whose chunk was complete at W0's release takes a chunk redrawn among the
        # chunks still incomplete there; drawn_chunk keeps the seed's draw.
        self.drawn_chunk = chunk
        self.anchor = ""
        self.anchor_rise = -1
        # Set at the opening of a drawn window: the pin was low (released) on the rise before,
        # the launched chunks not yet equal to their source, and the read beats its chunk still
        # owes.
        self.after_release = False
        self.incomplete_at_open: list[str] = []
        self.beats_left_at_open = -1

    def cells(self) -> str:
        if self.idx == 0:
            return f"W0(chunk=C0 pinned len={self.length})"
        redrawn = f" redrawn from C{self.drawn_chunk}" if self.drawn_chunk != self.chunk else ""
        return (
            f"W{self.idx}(chunk=C{self.chunk}{redrawn} opens {self.offset} rises after its "
            f"chunk's first AR or R beat after W0's release len={self.length})"
        )


class smc_dma_backpressure_rand_test_seq(SmcCsrSeq):
    """Five to eight queued chunks under a pinned hold and one to three drawn re-holds."""

    def __init__(self, name: str = "smc_dma_backpressure_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.sampler: _Sampler | None = None
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.chunks: list[_Chunk] = []
        self.wins: list[_Win] = []
        self.active = 0
        self.baseline = -1
        self.ready_before = -1
        self.ready_after = -1
        self.done_polls = 0
        self.launch_bound_ns = 0
        self.launches_done = False
        self.pending_launch_rise = -1
        self.timeout_paths: list[str] = []
        self.draw_attempts = 0

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        self.chk_ids.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    @property
    def _s(self) -> _Sampler:
        assert self.sampler is not None, "sampler not started"
        return self.sampler

    def _drawn(self) -> str:
        chunks = " ".join(f"C{c.idx}={c.length}B" for c in self.chunks)
        return f"{len(self.chunks)} chunks {chunks}; {' '.join(w.cells() for w in self.wins)}"

    def _draw_once(self) -> bool:
        n_desc = self.rng.randint(DESC_MIN, DESC_MAX)
        self.chunks = [_Chunk(i, self.rng.choice(CHUNK_LENGTHS)) for i in range(n_desc)]
        self.wins = [_Win(0, 0, 0, self.rng.randint(WIN_LEN_MIN, WIN_LEN_MAX))]
        n_win = self.rng.randint(WIN_MIN, WIN_MAX)
        for i in range(1, n_win + 1):
            chunk = self.rng.randrange(n_desc)
            offset = self.rng.randint(WIN_REOPEN_MIN, WIN_REOPEN_MAX)
            length = self.rng.randint(WIN_LEN_MIN, WIN_LEN_MAX)
            self.wins.append(_Win(i, chunk, offset, length))
        return all(self._beats_of(w.chunk) >= w.offset + 2 for w in self.wins[1:])

    def _beats_of(self, idx: int) -> int:
        return self.chunks[idx].length // BEAT_BYTES

    def _draw(self) -> None:
        for attempt in range(1, DRAW_BOUND + 1):
            if self._draw_once():
                break
        else:
            raise AssertionError(f"no pass within {DRAW_BOUND} draws: {self._drawn()}")
        self.draw_attempts = attempt
        n_desc = len(self.chunks)
        assert n_desc >= F2M_FIFO_DEPTH + 1, f"{n_desc} descriptors, fewer than five"
        assert all(self._beats_of(w.chunk) >= w.offset + 2 for w in self.wins[1:])
        assert all(c.length in CHUNK_LENGTHS for c in self.chunks)
        assert all(WIN_LEN_MIN <= w.length <= WIN_LEN_MAX for w in self.wins)
        assert WIN_MIN <= len(self.wins) - 1 <= WIN_MAX, f"{len(self.wins) - 1} drawn windows"
        assert all(WIN_REOPEN_MIN <= w.offset <= WIN_REOPEN_MAX for w in self.wins[1:])
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %s (draw %d of at most %d)",
            self.seed,
            self._drawn(),
            self.draw_attempts,
            DRAW_BOUND,
        )

    async def _pass_all(self) -> None:
        for name, addr, value in (
            ("IN_START", INBOUND0_START, 0),
            ("IN_END", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("IN_CFG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("OUT_START", OUTBOUND0_START, 0),
            ("OUT_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"PASS_{name}", addr, value, length=8)

    def _delivered(self, c: _Chunk) -> bool:
        return bytes(self._responder.read(c.dst, c.length)) == c.payload

    async def _first_hold(self, clk) -> str:
        """Hold until every launch read has returned, or a launch read is held past its bound."""
        while not self.launches_done:
            pending = self.pending_launch_rise
            if pending >= 0 and self._s.rises - pending > HELD_LAUNCH_RISES:
                return f"a launch read pending {HELD_LAUNCH_RISES} rises"
            await RisingEdge(clk)
        return "every launch read returned"

    def _incomplete(self) -> list[str]:
        return [x.name for x in self.chunks if x.id != -1 and not self._delivered(x)]

    def _ars_of(self, c: _Chunk) -> list[int]:
        lo = c.src & ~(BEAT_BYTES - 1)
        return [i for i, (addr, _, _) in enumerate(self._s.ar) if lo <= addr < c.src + c.length]

    def _beats_left(self, c: _Chunk) -> int:
        ars = set(self._ars_of(c))
        got = sum(1 for i, _ in self._s.r_beats if i in ars)
        return c.length // BEAT_BYTES - got

    def _first_beat(self, c: _Chunk, after: int) -> tuple[str, int]:
        """The first AR handshake or R beat of the chunk on a rise after `after`."""
        ars = self._ars_of(c)
        seen = [("AR", self._s.ar[i][2]) for i in ars if self._s.ar[i][2] > after]
        seen += [("R beat", r) for i, r in self._s.r_beats if i in ars and r > after]
        return min(seen, key=lambda x: x[1]) if seen else ("", -1)

    async def _anchor(self, w: _Win, release_rise: int) -> None:
        """Wait for the first AR or R beat of the window's chunk after W0's release, then for
        the window's drawn number of rises."""
        clk = cocotb.top.clk_smc_i
        c = self.chunks[w.chunk]
        for _ in range(ANCHOR_WAIT_RISES):
            w.anchor, w.anchor_rise = self._first_beat(c, release_rise)
            if w.anchor_rise >= 0:
                break
            await FallingEdge(clk)
        assert w.anchor_rise >= 0, (
            f"{w.cells()}: no AR or R beat of C{w.chunk} within {ANCHOR_WAIT_RISES} rises "
            f"after W0's release; {self._drawn()}"
        )
        while self._s.rises < w.anchor_rise + w.offset:
            await FallingEdge(clk)
        await self._window(w)

    def _start_drawn(self) -> None:
        """At W0's release: redraw the chunk of a drawn window whose chunk is already complete
        among the chunks still incomplete that carry the window's offset plus two read beats,
        then start every drawn window."""
        release_rise = self._s.rises
        incomplete = [x.idx for x in self.chunks if x.name in self.wins[0].undelivered]
        for w in self.wins[1:]:
            if w.chunk not in incomplete:
                fit = [i for i in incomplete if self._beats_of(i) >= w.offset + 2]
                assert fit, (
                    f"{w.cells()}: no chunk incomplete at W0's release carries {w.offset} + 2 "
                    f"read beats (incomplete {incomplete}); {self._drawn()}"
                )
                w.chunk = self.rng.choice(fit)
            assert w.chunk in incomplete and self._beats_of(w.chunk) >= w.offset + 2
            cocotb.start_soon(self._anchor(w, release_rise))

    def _stall(self, w: _Win, c: _Chunk) -> None:
        """Source ARs of the chunk accepted under the window, and held rises on which an
        accepted AR of the chunk still owed R beats."""
        ars = self._ars_of(c)
        w.ar_held = sum(
            1 for i in ars if self._s.ar[i][1] and w.open_rise < self._s.ar[i][2] <= w.close_rise
        )
        w.r_held = sum(
            1
            for rise, done, n_ar in self._s.held
            if w.open_rise < rise <= w.close_rise and any(done <= i < n_ar for i in ars)
        )

    async def _window(self, w: _Win) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        if w.idx == 0:
            await FallingEdge(clk)
        c = self.chunks[w.chunk]
        if w.idx:
            w.after_release = self.active == 0
            w.incomplete_at_open = self._incomplete()
            w.beats_left_at_open = self._beats_left(c)
        self.active += 1
        dut.tb_output_axi_resp_hold.value = 1
        w.open_ps = int(get_sim_time("ps"))
        w.open_rise = self._s.rises
        w.opened = True
        if w.idx == 0:
            w.release_cause = await self._first_hold(clk) + f", then {w.length} rises"
        await ClockCycles(clk, w.length)
        await FallingEdge(clk)
        w.close_rise = self._s.rises
        w.launched = c.id != -1
        self._stall(w, c)
        w.undelivered = self._incomplete()
        if w.idx == 0:
            w.launched_under = sum(1 for x in self.chunks if x.id != -1)
        w.outstanding = w.launched and (w.ar_held > 0 or w.r_held > 0) and not self._delivered(c)
        self.active -= 1
        if self.active == 0:
            dut.tb_output_axi_resp_hold.value = 0
        w.close_ps = int(get_sim_time("ps"))
        w.closed = True
        if w.idx == 0:
            self._start_drawn()

    async def _wait(self, what: str, cond, rises: int) -> None:
        for _ in range(rises):
            if cond():
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        assert cond(), f"{what} not reached within {rises} clk_smc_i rises"

    async def _program(self, c: _Chunk) -> None:
        for reg, value in (
            (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            (DMA_CTRL_DST_ADDRESS_LO, c.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, c.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, c.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, c.src >> 32),
            (DMA_CTRL_LENGTH_LO, c.length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, 0),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, 0),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, 1),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{c.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, c: _Chunk) -> None:
        """Before the first chunk start W0; read NEXT_ID_0 once under the launch-read bound."""
        if c.idx == 0:
            w0 = self.wins[0]
            cocotb.start_soon(self._window(w0))
            await self._wait(f"{w0.cells()} opening", lambda: w0.opened, OPEN_WAIT_RISES)
        c.held_at_issue = self.active > 0
        item = SmcSysAxiItem(f"rd_{c.name}_NEXT_ID")
        item.op = SmcSysAxiOp.READ
        item.addr = DMA_CTRL_NEXT_ID_0
        item.length = 4
        item.timeout_ns = self.launch_bound_ns
        t0 = int(get_sim_time("ps"))
        self.pending_launch_rise = self._s.rises
        await self.start_item(item)
        await self.finish_item(item)
        self.pending_launch_rise = -1
        self.accesses += 1
        period_ps = self.cfg.smc_clk_period_ns * 1000
        c.launch_rises = int((int(get_sim_time("ps")) - t0) // period_ps)
        c.id = item.rdata
        c.status_after_launch = await self.csr_read(f"{c.name}_STATUS", DMA_CTRL_STATUS_0)

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        dut.tb_output_axi_resp_hold.value = 0
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self._draw()
        period = self.cfg.smc_clk_period_ns
        self.launch_bound_ns = max(self.cfg.axi_timeout_ns, math.ceil(LAUNCH_BOUND_RISES * period))
        self.sampler = _Sampler(dut)
        cocotb.start_soon(self.sampler.run())
        await self._pass_all()
        self.baseline = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        self.ready_before = (await self.csr_read("STATUS_BEFORE", DMA_CTRL_STATUS_0)) & READY_MASK
        cocotb.log.info(
            "DONE_0 baseline %d; STATUS_0[7:0] before the first launch 0x%02x beside the control "
            "word 0x%02x (logged, not graded)",
            self.baseline,
            self.ready_before,
            READY_MASK,
        )
        self._mark("S1")

    async def _s2(self) -> None:
        for c in self.chunks:
            self._responder.write(c.src, c.payload)
            self._responder.write(c.dst - GUARD, bytes([GUARD_BYTE]) * GUARD)
            self._responder.write(c.dst, bytes([POISON]) * c.length)
            self._responder.write(c.dst + c.length, bytes([GUARD_BYTE]) * GUARD)
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S2")

    async def _s3(self) -> None:
        cocotb.log.info(
            "hold windows armed on tb_output_axi_resp_hold, W0 before the first launch read, "
            "each drawn window counted from W0's release: %s",
            " ".join(w.cells() for w in self.wins),
        )
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S3")

    async def _s4(self) -> list[tuple[str, str]]:
        for c in self.chunks:
            await self._program(c)
            await self._launch(c)
        self.launches_done = True
        await self._wait(
            "every hold window released",
            lambda: all(w.closed for w in self.wins),
            CLOSE_WAIT_RISES,
        )
        hold = cocotb.top.tb_output_axi_resp_hold.value
        assert hold.is_resolvable and int(hold) == 0, f"hold reads {hold} after the release"
        launched = len(self.chunks)
        assert launched >= F2M_FIFO_DEPTH + 1, f"{launched} descriptors launched, want >= 5"
        first = self.wins[0]
        need = min(launched, F2M_FIFO_DEPTH)
        assert len(first.undelivered) >= need, (
            f"{len(first.undelivered)} launched chunks undelivered at the release of "
            f"{first.cells()} ({first.release_cause}): {first.undelivered}, want at least "
            f"min({launched}, {F2M_FIFO_DEPTH}) = {need}; {self._drawn()}"
        )
        for w in self.wins[1:]:
            name = f"C{w.chunk}"
            assert name in w.incomplete_at_open and w.outstanding, (
                f"{w.cells()}: its chunk {name} was not incomplete and stalled under it "
                f"(incomplete at the opening {w.incomplete_at_open}, read beats left "
                f"{w.beats_left_at_open}, source ARs accepted under the hold {w.ar_held}, held "
                f"rises with an R beat of {name} owed {w.r_held}, outstanding at release="
                f"{w.outstanding}); {self._drawn()}"
            )
        under = [w for w in self.wins if w.outstanding]
        reheld = [w for w in self.wins[1:] if w.after_release and w.incomplete_at_open]
        assert reheld, (
            "no drawn window opened after a release while a launched chunk was incomplete: "
            + "; ".join(
                f"{w.cells()} after_release={w.after_release} incomplete {w.incomplete_at_open}"
                for w in self.wins[1:]
            )
            + f"; {self._drawn()}"
        )
        self._mark("S4")
        wins = "; ".join(
            f"{w.cells()}"
            + (
                f" opened {w.offset} rises after its {w.anchor} at rise {w.anchor_rise}, "
                f"C{w.chunk} incomplete at the opening with {w.beats_left_at_open} read beats "
                f"left"
                if w.idx
                else ""
            )
            + f" launched={w.launched} stall under the hold: source ARs accepted {w.ar_held}, "
            f"rises with an R beat owed {w.r_held}; outstanding at release={w.outstanding}"
            + (
                f"; opened after a release={w.after_release} with launched chunks incomplete "
                f"{w.incomplete_at_open}"
                if w.idx
                else ""
            )
            for w in self.wins
        )
        launches = "; ".join(
            f"{c.name} id {c.id} launch read {c.launch_rises} rises held_at_issue="
            f"{c.held_at_issue} STATUS_0 0x{c.status_after_launch:x}"
            for c in self.chunks
        )
        return [
            (
                "CHK-DBP-QUEUE",
                f"{launched} descriptors programmed and launched; {first.launched_under} "
                f"launch reads accepted under W0; {len(first.undelivered)} launched chunks "
                f"undelivered at its release ({first.release_cause}), at least min({launched}, "
                f"{F2M_FIFO_DEPTH}) = {need} for the {F2M_FIFO_DEPTH}-entry request FIFO: "
                f"{first.undelivered}; every drawn window's chunk incomplete and stalled under "
                f"it, {len(under)} hold window(s) released with their chunk outstanding; "
                f"{len(reheld)} drawn window(s) opened after a release while a launched chunk "
                f"was incomplete: {wins}; printed, not compared: "
                f"{launches}; drawn={self._drawn()}",
            )
        ]

    async def _s5(self) -> list[tuple[str, str]]:
        last = self.chunks[-1].id
        done = -1
        for poll in range(1, POLL_LIMIT + 1):
            done = await self.csr_read("DONE_POLL", DMA_CTRL_DONE_0)
            if done == last:
                self.done_polls = poll
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        assert done == last, (
            f"DONE_0 reads {done}, not the last returned id {last}, after {POLL_LIMIT} polls of "
            f"{POLL_CYCLES} clk_smc_i cycles; {self._drawn()}"
        )
        prev = self.baseline
        for c in self.chunks:
            want = _next_id(prev)
            assert c.id == want, f"{c.name}: NEXT_ID_0 returned {c.id}, want {want} after {prev}"
            prev = c.id
        for c in self.chunks:
            got = bytes(self._responder.read(c.dst, c.length))
            if got != c.payload:
                idx = next(i for i, (a, b) in enumerate(zip(got, c.payload)) if a != b)
                raise AssertionError(
                    f"{c.name}: destination byte 0x{c.dst + idx:x} is 0x{got[idx]:02x}, want "
                    f"0x{c.payload[idx]:02x} ({c.length} bytes); {self._drawn()}"
                )
            want = bytes([GUARD_BYTE]) * GUARD
            before = bytes(self._responder.read(c.dst - GUARD, GUARD))
            after = bytes(self._responder.read(c.dst + c.length, GUARD))
            assert before == want and after == want, (
                f"{c.name}: guard words changed: before={before.hex()} after={after.hex()}"
            )
            src = bytes(self._responder.read(c.src, c.length))
            assert src == c.payload, f"{c.name}: source bytes changed"
        self.ready_after = (await self.csr_read("STATUS_AFTER", DMA_CTRL_STATUS_0)) & READY_MASK
        self._mark("S5")
        ids = ", ".join(f"{c.name}={c.id}" for c in self.chunks)
        total = sum(c.length for c in self.chunks)
        return [
            (
                "CHK-DBP-BYTES",
                f"all {len(self.chunks)} chunks ({total} bytes) equal their source at the "
                f"destination after the last hold released, every guard word kept 0x"
                f"{GUARD_BYTE:02x} and every source is unchanged; drawn={self._drawn()}",
            ),
            (
                "CHK-DBP-IDS",
                f"every launch read completed within {self.launch_bound_ns} ns and returned the "
                f"previous id + 1 from DONE_0 baseline {self.baseline}: {ids}; DONE_0 reached "
                f"the last id {last} in {self.done_polls} polls (bound {POLL_LIMIT}); "
                f"drawn={self._drawn()}",
            ),
            (
                "CHK-DBP-READY",
                f"logged control, not graded: STATUS_0[7:0] before the first launch "
                f"0x{self.ready_before:02x} and after the last id retired "
                f"0x{self.ready_after:02x}, beside the control word 0x{READY_MASK:02x}",
            ),
        ]

    async def _s6(self) -> None:
        for name, addr, value in (
            ("IN_CFG", INBOUND0_FILTER_CONFIG, RESET_CFG),
            ("IN_START", INBOUND0_START, RESET_START),
            ("IN_END", INBOUND0_END, RESET_END),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, RESET_CFG),
            ("OUT_START", OUTBOUND0_START, RESET_START),
            ("OUT_END", OUTBOUND0_END, RESET_END),
        ):
            await self.csr_write(f"RESTORE_{name}", addr, value, length=8)
            await self.csr_read(f"RESTORE_{name}", addr, expected=value, length=8)
        self._mark("S6")

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        for step, fn in (("S4", self._s4), ("S5", self._s5)):
            for chk, text in await fn():
                self._chk(step, chk, text)
        await self._s6()
        period = self.cfg.smc_clk_period_ns
        self.timeout_paths = [
            f"fuse sense <= {FUSE_SENSE_BOUND} clk_smc_i rises",
            f"launch read <= {self.launch_bound_ns} ns ({LAUNCH_BOUND_RISES} clk_smc_i rises "
            f"at {period} ns, floor {self.cfg.axi_timeout_ns} ns)",
            f"W0 opening <= {OPEN_WAIT_RISES} rises, every release <= {CLOSE_WAIT_RISES} "
            f"rises after the last launch, W0 held past every launch read or a launch read "
            f"pending {HELD_LAUNCH_RISES} rises",
            f"a drawn window's first AR or R beat of its chunk <= {ANCHOR_WAIT_RISES} rises "
            f"after W0's release",
            f"DONE_0 poll <= {POLL_LIMIT} reads {POLL_CYCLES} clk_smc_i cycles apart",
            f"SEP_IN driver guard {self.cfg.axi_timeout_ns} ns per other access",
        ]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self.timeout_paths),
            "; ".join(self.timeout_paths),
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [s for s, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_steps == list(CHECKS), f"checker lines {self.chk_steps}"
        aw = self._s.aw
        per = [sum(1 for a in aw if c.dst - GUARD <= a < c.dst + c.length) for c in self.chunks]
        assert all(n >= 1 for n in per), f"AW handshakes per descriptor {per}"
        assert self._s.orphan_beats == 0, (
            f"{self._s.orphan_beats} R beats with no accepted AR owing them; {self._drawn()}"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1 < ... < S6, checker lines in step order each after "
            "its own step; AW handshakes per descriptor %s (each at least 1), AR %d, R beats "
            "%d over %d completed bursts, each owed by an accepted AR, B %d; checker lines %s; "
            "stamps %s",
            per,
            len(self._s.ar),
            len(self._s.r_beats),
            self._s.done,
            self._s.b,
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
