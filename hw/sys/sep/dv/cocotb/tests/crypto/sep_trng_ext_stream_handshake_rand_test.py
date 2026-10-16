# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The external TRNG stream handshake, the source select and its lock, and the pool pop.

Contract (``hw/sys/sep/doc/trng.adoc``, Distribution and Source Selection;
``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``, EXT_TRNG_SRC_SEL and
EXT_TRNG_SRC_SEL_LOCK; ``hw/sys/sep/doc/interrupts.adoc``, source 17;
``hw/sys/sep/doc/entropy_pool.adoc``, Access Policy;
``hw/sys/sep/regs/gen/adoc/blocks/sep_entropy_pool.adoc``, STATUS and DATA):
  * An external stream has tvalid, tready, 32-bit tdata and 4-bit tstrb; a source
    holds tvalid and tdata until tready. The mux gives each external beat a tuser
    of 1, so each word a client accepts carries edn_fips = 1.
  * The selected sink receives each accepted word unchanged and in order. The
    crypto and pool adapters accept only strobe 0xF; a partial strobe stalls them.
  * ``ext_trng_irq_i`` is PIC source 17 (vector bit 16).
  * ``EXT_TRNG_SRC_SEL.sel`` bit N selects the source of stream N (0 Key Manager,
    1 crypto, 2 pool): 0 internal, 1 external. ``EXT_TRNG_SRC_SEL_LOCK.lock``
    (RW1S) freezes the select until the CPU-control bank resets; a TRNG reset
    alone does not clear it.
  * An unselected external input receives ready high and its beats are
    discarded. An unselected internal endpoint is back-pressured and keeps its
    queued data. A 64-bit read of the pool ``DATA`` pops one entry.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. Baseline ``SW_RESET_N`` = 0x24 (TRNG and AES released;
the Key Manager and the other engines held). The external stream driver and
monitor (``env/sep_ext_trng_stream.py``) drive the three streams; a per-clock
trace of this leaf reads the external port taps, the post-mux probes
(``axis1_*``, ``axis2_*``, ``km_entropy_*``), the internal DRBG endpoint tap
(``drbg_int_*``) and the client acknowledge probes in the same clock phase as the
driver (after the falling edge, the values the next rising edge sees).

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the stream order, the beat counts (stream 1: 8 to 96; stream 2: even,
8 to 64), the gap pattern (back-to-back, random gaps of 0 to 20 clocks, or one
long gap), the partial strobe (0x0 to 0xE), the hold H (16 to 64 clocks), the hold
window (64 to 256 clocks), the unique non-zero beat words, the select values d, s,
a and b, the idle gap before the lock write (0 to 32 clocks), the initial pool fill
L (0 to 32 pairs) and the random pool operations (20 to 60).

Checkers: CHK-SEL-RW, CHK-EXT-XFER, CHK-EXT-STRB, CHK-EXT-DROP, CHK-EXT-BP,
CHK-EXT-IRQ, CHK-SEL-READY, CHK-SEL-HOLD, CHK-SEL-LOCK, CHK-SEL-LOCKFIRST,
CHK-SEL-GLOBAL, CHK-POOL-DATA (contracts in the docstring of each leg).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_ext_trng_stream import SepExtTrngStream
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_pic_map import SRC_TIED, vec_bit
from env.sep_reg_meta import SEP_CPU_CTRL
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_monitor_life import MonitorLife
from seq_lib.sep_aes_seq import AES_TRIGGER, AES_TRIGGER_PRNG_RESEED, SepAes
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_entropy_pool_seq import (
    POOL_POP,
    RESP_OKAY,
    SepEntropyPool,
    pool_level,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_RESET_DEFAULT, SepSwReset

TEST = "sep_trng_ext_stream_handshake_rand_test"

SEL_ADDR = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")
LOCK_ADDR = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL_LOCK")
SEL_MASK = SEP_CPU_CTRL.field_mask("EXT_TRNG_SRC_SEL", "sel")
SEL_RESET = SEP_CPU_CTRL.reset("EXT_TRNG_SRC_SEL")
LOCK_MASK = SEP_CPU_CTRL.field_mask("EXT_TRNG_SRC_SEL_LOCK", "lock")

# PIC source 17, the external TRNG interrupt (interrupts.adoc), on vector bit 16.
VEC_EXT_IRQ = vec_bit(SRC_TIED)

STRB_FULL = 0xF
# The pool holds 32 entries of 64 bits (trng.adoc; entropy_pool.adoc).
POOL_DEPTH = 32
# Back-pressure bound in pairs and ready-leg bound in accepted beats (test parameters).
BP_PAIR_BOUND = 64
READY_BEAT_BOUND = 2000
# Engines held by the baseline: SW_RESET_N = 0x24 keeps TRNG and AES released.
PARKED = ("otbn", "hmac", "kmac", "abr")
GAP_PATTERNS = ("b2b", "random", "long")
RANDOM_GAP_MAX = 20
LONG_GAP = 200
IRQ_BOUND = 64
# Clocks that ext_trng_irq_i keeps each level after vector bit 16 follows it.
IRQ_HOLD = 8
# Outer caps of a first measurement (design rule: 20 x the clean value of the logs).
TRNG_RESET_CAP = 4_000
SETTLE_CAP = 20_000
DRAIN_WINDOW = 4_000
STATUS_AGREE_READS = 64
# Pool-path settle: no stream-2 transfer (port or post-mux) and no pool EDN
# acknowledge for this many clocks before a graded STATUS read. A pool word takes
# about 4 clocks from the adapter to the pool (stage FIFO, endpoint, EDN handshake);
# the window is 16 x that. A word that lands later shows as a level mismatch.
POOL_QUIET = 64
STREAMS = (0, 1, 2)


# ----------------------------------------------------------------------------- plan
@dataclass(frozen=True)
class StreamPlan:
    stream: int
    d: int
    s: int
    gap_pattern: str
    xfer_words: tuple[int, ...]
    xfer_gaps: tuple[int, ...]
    strobe: int
    ctrl_word: int
    part_words: tuple[int, ...]
    recov_word: int
    drop_words: tuple[int, ...]
    bp_pairs: tuple[int, ...]
    ready_words: tuple[tuple[int, ...], ...]
    hold_win: int
    pop_sel: int
    fill_pairs: tuple[int, ...]
    ops: tuple[str, ...]
    feed_pairs: tuple[int, ...]

    @property
    def bit(self) -> int:
        return 1 << self.stream

    def describe(self) -> str:
        return (
            f"stream{self.stream}:d=0x{self.d:x},s=0x{self.s:x},beats={len(self.xfer_words)},"
            f"gap={self.gap_pattern},strobe=0x{self.strobe:x},hold_win={self.hold_win},"
            f"L={len(self.fill_pairs)},ops={len(self.ops)}"
        )


@dataclass(frozen=True)
class Plan:
    seed: int
    order: tuple[int, ...]
    hold: int
    streams: dict[int, StreamPlan] = field(hash=False)
    a: int = 0
    b: int = 0
    idle_gap: int = 0

    def describe(self) -> str:
        parts = " ".join(self.streams[i].describe() for i in self.order)
        return (
            f"order={list(self.order)} H={self.hold} {parts} a=0x{self.a:x} b=0x{self.b:x} "
            f"idle_gap={self.idle_gap}"
        )


class _Words:
    """Unique non-zero 32-bit words; no word repeats, so no word equals a neighbour."""

    def __init__(self, rng: SepSeededRng) -> None:
        self.rng = rng
        self.used: set[int] = set()

    def take(self, n: int) -> tuple[int, ...]:
        out = []
        while len(out) < n:
            w = self.rng.getrandbits(32)
            if w and w not in self.used:
                self.used.add(w)
                out.append(w)
        return tuple(out)


def _draw_sel(rng: SepSeededRng, *, must: int = 0, avoid: tuple[int, ...] = ()) -> int:
    while True:
        v = rng.randrange(0, SEL_MASK + 1) | must
        if v not in avoid:
            return v


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    words = _Words(rng)
    order = [1, 2]
    rng.shuffle(order)
    hold = rng.randrange(16, 65)
    held = SEL_RESET
    streams: dict[int, StreamPlan] = {}
    for i in order:
        bit = 1 << i
        d = _draw_sel(rng, avoid=(held,))
        s = _draw_sel(rng, must=bit, avoid=(d,))
        n = rng.randrange(8, 97) if i == 1 else rng.randrange(8, 65, 2)
        pattern = rng.choice(GAP_PATTERNS)
        if pattern == "random":
            gaps = tuple(rng.randrange(0, RANDOM_GAP_MAX + 1) for _ in range(n))
        else:
            gaps = tuple(0 for _ in range(n))
        xfer = words.take(n)
        strobe = rng.randrange(0, STRB_FULL)
        ctrl_word, recov_word = words.take(2)
        part = words.take(2)
        drop = words.take(n)
        bp = words.take(BP_PAIR_BOUND + 1)
        ready = tuple(words.take(READY_BEAT_BOUND + 1) for _ in STREAMS)
        hold_win = rng.randrange(64, 257)
        # Pop golden leg (stream 2): bit 2 set, bit 1 clear, bit 0 from s.
        pop_sel = (s & 0b001) | 0b100
        fill = words.take(rng.randrange(0, 33))
        n_ops = rng.randrange(20, 61)
        ops = tuple(rng.choice(("pop", "status", "feed")) for _ in range(n_ops))
        # Feeds: the corner run (at most 34 - L + 1 feeds) plus the drawn feeds.
        feeds = words.take(POOL_DEPTH + 2 + n_ops)
        streams[i] = StreamPlan(
            i, d, s, pattern, xfer, gaps, strobe, ctrl_word, part, recov_word, drop, bp,
            ready, hold_win, pop_sel, fill, ops, feeds,
        )  # fmt: skip
        # The value held before the next select write of the plan: the hold leg
        # writes 0x7 with the bit of the stream cleared; the pop leg of stream 2
        # writes pop_sel after it.
        held = pop_sel if i == 2 else (SEL_MASK & ~bit)
    a = _draw_sel(rng, avoid=(SEL_RESET,))
    b = _draw_sel(rng, avoid=(a,))
    idle_gap = rng.randrange(0, 33)
    return Plan(seed, tuple(order), hold, streams, a, b, idle_gap)


# ----------------------------------------------------------------------------- trace
def _bitstr(sig) -> str:
    value = sig.value
    bits = getattr(value, "binstr", None)
    return (bits if bits is not None else str(value)).strip()


def _known(sig) -> int | None:
    bits = _bitstr(sig)
    return int(bits, 2) if bits and all(c in "01" for c in bits) else None


@dataclass(frozen=True)
class Row:
    """One clock of the trace, sampled after the falling edge (None = X/Z)."""

    clk: int
    ev: int | None  # ext_trng_tvalid_o[2:0]
    er: int | None  # ext_trng_tready_o[2:0]
    ed: int | None  # ext_trng_tdata_o[95:0]
    pv: tuple  # post-mux tvalid of streams 0..2 (km_entropy, axis1, axis2)
    pr: tuple  # post-mux tready
    pd: tuple  # post-mux tdata
    iv: int | None  # drbg_int_tvalid_o[2:0]
    ir: int | None  # drbg_int_tready_o[2:0]
    idata: int | None  # drbg_int_tdata_o[95:0]
    cack: int | None  # crypto_edn_ack_o[3:0]
    cfips: int | None  # crypto_edn_fips_o[3:0]
    creq: int | None  # crypto_edn_req_o[3:0]
    pack: int | None  # pool_edn_ack_o
    pfips: int | None  # pool_edn_fips_o


def _bit(v: int | None, i: int) -> int | None:
    return None if v is None else (v >> i) & 1


def _word(v: int | None, i: int) -> int | None:
    return None if v is None else (v >> (32 * i)) & 0xFFFF_FFFF


class _Trace:
    """Per-clock record of the stream taps and probes of this leaf.

    Samples after each falling edge of ``clk_i`` in the read-only phase, the phase of
    the external stream monitor. Running counters (``ext_xfers``, ``stall``) update
    on every clock; ``rows`` fills only between ``begin`` and ``end``.
    """

    def __init__(self, dut) -> None:
        self.dut = dut
        self.clk = 0
        self.rows: list[Row] = []
        self.recording = False
        self.ext_xfers = [0, 0, 0]
        self.stall = [0, 0, 0]
        # Clocks since the last stream-2 transfer or pool EDN acknowledge.
        self.pool_quiet = 0
        self.life = MonitorLife("EXT-STREAM-TRACE", lambda: self.clk)
        d = dut
        self._post = (
            (d.km_entropy_tvalid_o, d.km_entropy_tready_o, d.km_entropy_tdata_o),
            (d.axis1_tvalid_o, d.axis1_tready_o, d.axis1_tdata_o),
            (d.axis2_tvalid_o, d.axis2_tready_o, d.axis2_tdata_o),
        )

    def start(self) -> "_Trace":
        self.life.start(self._run())
        return self

    async def stop(self) -> None:
        await self.life.stop()

    def begin(self) -> int:
        self.rows = []
        self.recording = True
        return self.clk

    def end(self) -> list[Row]:
        self.recording = False
        rows, self.rows = self.rows, []
        return rows

    async def _run(self) -> None:
        d = self.dut
        while True:
            await FallingEdge(d.clk_i)
            await ReadOnly()
            self.clk += 1
            ev = _known(d.ext_trng_tvalid_o)
            er = _known(d.ext_trng_tready_o)
            for i in STREAMS:
                v, r = _bit(ev, i), _bit(er, i)
                if v == 1 and r == 1:
                    self.ext_xfers[i] += 1
                    self.stall[i] = 0
                elif v == 1 and r == 0:
                    self.stall[i] += 1
                else:
                    self.stall[i] = 0
            pool_event = (
                (_bit(ev, 2) == 1 and _bit(er, 2) == 1)
                or (_known(d.axis2_tvalid_o) == 1 and _known(d.axis2_tready_o) == 1)
                or _known(d.pool_edn_ack_o) != 0
            )
            self.pool_quiet = 0 if pool_event else self.pool_quiet + 1
            if not self.recording:
                continue
            self.rows.append(
                Row(
                    self.clk,
                    ev,
                    er,
                    _known(d.ext_trng_tdata_o),
                    tuple(_known(p[0]) for p in self._post),
                    tuple(_known(p[1]) for p in self._post),
                    tuple(_known(p[2]) for p in self._post),
                    _known(d.drbg_int_tvalid_o),
                    _known(d.drbg_int_tready_o),
                    _known(d.drbg_int_tdata_o),
                    _known(d.crypto_edn_ack_o),
                    _known(d.crypto_edn_fips_o),
                    _known(d.crypto_edn_req_o),
                    _known(d.pool_edn_ack_o),
                    _known(d.pool_edn_fips_o),
                )
            )


def ext_xfers(rows: list[Row], i: int) -> list[int | None]:
    """Words that complete at external port i (tvalid and tready high)."""
    return [_word(r.ed, i) for r in rows if _bit(r.ev, i) == 1 and _bit(r.er, i) == 1]


def post_xfers(rows: list[Row], i: int) -> list[int | None]:
    """Words that complete at the post-mux probe of stream i."""
    return [r.pd[i] for r in rows if r.pv[i] == 1 and r.pr[i] == 1]


def _final_stall(rows: list[Row], i: int, min_len: int) -> int | None:
    """Index of the first row of the trailing run of rows where stream i has tvalid 1
    and tready 0, or None when that run is shorter than ``min_len``."""
    k = len(rows)
    while k > 0 and _bit(rows[k - 1].ev, i) == 1 and _bit(rows[k - 1].er, i) == 0:
        k -= 1
    return k if len(rows) - k >= min_len else None


# ----------------------------------------------------------------------------- leaf
class _Reg(SepAxiRegDriver):
    _DRIVER_TAG = "SEL"


@pyuvm.test()
class sep_trng_ext_stream_handshake_rand_test(sep_base_test):
    """External stream handshake, source select and lock, pool pop golden."""

    required_evidence = (
        "CHK-SEL-RW",
        "CHK-EXT-XFER",
        "CHK-EXT-STRB",
        "CHK-EXT-DROP",
        "CHK-EXT-BP",
        "CHK-EXT-IRQ",
        "CHK-SEL-READY",
        "CHK-SEL-HOLD",
        "CHK-SEL-LOCK",
        "CHK-SEL-LOCKFIRST",
        "CHK-SEL-GLOBAL",
        "CHK-POOL-DATA",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        # Step 1: the select and the lock are the first accesses of the leaf.
        await self.release_no_cpu_reset(park=PARKED)
        await self.wait_fuse_sense()
        self.reg = _Reg(self)
        sel0 = await self.reg._rd(SEL_ADDR)
        lock0 = await self.reg._rd(LOCK_ADDR)
        self.swrst = SepSwReset(self)
        await self.swrst.park(*PARKED)
        await ClockCycles(dut.clk_i, 2)
        self._jtag_sw_rst_hold(PARKED, False)
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)

        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.chk.obs("SEL-RESET", sel=f"0x{sel0 & SEL_MASK:x}", lock=lock0 & LOCK_MASK)
        self.aes = SepAes(self)
        self.pool = SepEntropyPool(self)
        self.trace = _Trace(dut).start()
        self.ext = SepExtTrngStream(dut, logger=self.logger).start(streams=STREAMS)
        self.sb = None
        self.xfer_seen: dict[int, int] = {}
        try:
            for i in plan.order:
                await self._stream_pass(plan.streams[i])
            await self._irq_leg()
            await self._lock_leg()
            await self._global_leg()
            await self._lockfirst_leg()
        finally:
            close_graded_window(self.logger)
            if self.sb is not None:
                self.sb.stop()
        await self.ext.stop()
        await self.trace.stop()
        self.chk.finish()

    # --- bus and waits ---------------------------------------------------------------
    async def _sel(self, value: int) -> int:
        await self.reg._wr(SEL_ADDR, value)
        return await self.reg._rd(SEL_ADDR) & SEL_MASK

    async def _clocks(self, n: int) -> None:
        if n > 0:
            await ClockCycles(cocotb.top.clk_i, n)

    async def _until(self, pred, bound: int) -> int | None:
        """Clocks until ``pred()`` holds (checked after each rising edge), or None."""
        for n in range(bound + 1):
            if pred():
                return n
            await RisingEdge(cocotb.top.clk_i)
        return None

    async def _wait_probe(self, sig, want_zero: bool, what: str) -> int:
        dut = cocotb.top
        for clk in range(TRNG_RESET_CAP):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if (self.rd(sig, allow_unknown=True) == 0) == want_zero:
                return clk
        raise AssertionError(f"{what}: no change within {TRNG_RESET_CAP} clocks")

    async def _trng_reset(self, *, source_reset: int | None = None) -> None:
        """Bit 5 of SW_RESET_N to 0 then 1; wait for the fall of the reset probe.

        With ``source_reset`` the driver resets that source at the rise of the
        probe, together with the sink reset.
        """
        dut = cocotb.top
        if self.sb is not None:
            self.sb.stop()
            self.sb = None
        await self.swrst.park("trng")
        rise = await self._wait_probe(dut.trng_reset_active_probe_o, False, "trng reset rise")
        await RisingEdge(dut.clk_i)
        if source_reset is not None:
            dropped = await self.ext.source_reset(source_reset)
            self.logger.info("source reset stream=%d dropped=%d", source_reset, dropped)
        await self.swrst.release("trng")
        fall = await self._wait_probe(dut.trng_reset_active_probe_o, True, "trng reset fall")
        await RisingEdge(dut.clk_i)
        self.logger.info("TRNG reset: rise_clk=%d fall_clk=%d cap=%d", rise, fall, TRNG_RESET_CAP)

    async def _drop_source(self, *streams: int) -> None:
        """End of a leg: the source drops whatever it still holds or queues."""
        for i in streams:
            if self.ext.pending(i):
                await self.ext.source_reset(i)

    async def _settle_pairs(self, stream: int, target: int, bound: int) -> int | None:
        """Wait until ``target`` beats completed at port ``stream`` since the counter
        value at the call, or a beat stays pending H clocks. Returns the clocks or None
        on a stall."""
        base = self.trace.ext_xfers[stream]
        h = self.plan.hold
        n = await self._until(
            lambda: self.trace.ext_xfers[stream] - base >= target or self.trace.stall[stream] >= h,
            bound,
        )
        if n is None or self.trace.ext_xfers[stream] - base < target:
            return None
        return n

    async def _status_settled(self) -> tuple[int, int]:
        """STATUS after the pool path is quiet (``POOL_QUIET`` clocks with no stream-2
        transfer and no pool acknowledge, bound ``SETTLE_CAP``), then until two
        consecutive reads agree. Returns (level, reads); reads is -1 when the path
        never went quiet or no two consecutive reads agreed within the bound (the last
        level is returned and the caller's compare grades it)."""
        quiet = await self._until(lambda: self.trace.pool_quiet >= POOL_QUIET, SETTLE_CAP)
        prev = -1
        for n in range(1, STATUS_AGREE_READS + 1):
            lvl = pool_level(await self.pool.status())
            if lvl == prev:
                return lvl, (n if quiet is not None else -1)
            prev = lvl
        return prev, -1

    async def _pop(self) -> tuple[int, int]:
        seq = await self.pool.access(POOL_POP)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF_FFFF_FFFF

    # --- one stream ------------------------------------------------------------------
    async def _stream_pass(self, sp: StreamPlan) -> None:
        i = sp.stream
        await self._trng_reset()
        await self._select_leg(sp)
        await self._transfer_leg(sp)
        await self._strobe_leg(sp)
        await self._drop_leg(sp)
        if i == 2:
            await self._bp_leg(sp)
        await self._ready_leg(sp)
        await self._hold_leg(sp)
        if i == 2:
            await self._pop_leg(sp)

    async def _select_leg(self, sp: StreamPlan) -> None:
        """CHK-SEL-RW: a drawn select value reads back as written (RW)."""
        open_graded_window(TEST, self.logger)
        for v in (sp.d, sp.s):
            got = await self._sel(v)
            self.chk.ok("SEL-RW", got == v, stream=sp.stream, wrote=f"0x{v:x}", read=f"0x{got:x}")
        close_graded_window(self.logger)

    async def _feed(self, stream: int, words, gaps, pattern: str, bound: int) -> bool:
        """Offer ``words`` on ``stream``. Returns False when a beat stays pending H clocks."""
        if pattern == "b2b":
            self.ext.send(stream, words)
            return await self._settle_pairs(stream, len(words), bound) is not None
        half = len(words) // 2
        for k, (w, gap) in enumerate(zip(words, gaps, strict=True)):
            self.ext.send(stream, [w])
            if await self._settle_pairs(stream, 1, bound) is None:
                return False
            if pattern == "long" and k == half - 1:
                await self._clocks(LONG_GAP)
            else:
                await self._clocks(gap)
        return True

    async def _transfer_leg(self, sp: StreamPlan) -> None:
        """CHK-EXT-XFER: every beat that completes at the external port appears at the
        post-mux probe in order and value; each accepted word has edn_fips = 1. On stream
        2 the empty pool takes every beat with no stall."""
        i = sp.stream
        dut = cocotb.top
        open_graded_window(TEST, self.logger)
        self.trace.begin()
        if i == 1:
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
            self.chk.obs("EXT-AES-REQ", crypto_edn_req0=self.rd(dut.crypto_edn_req_o, 1))
        bound = len(sp.xfer_words) * (RANDOM_GAP_MAX + LONG_GAP + 16) + SETTLE_CAP
        done = await self._feed(i, sp.xfer_words, sp.xfer_gaps, sp.gap_pattern, bound)
        await self._clocks(8)
        rows = self.trace.end()
        await self._drop_source(i)
        close_graded_window(self.logger)
        ext = ext_xfers(rows, i)
        post = post_xfers(rows, i)
        if i == 1:
            fips = [_bit(r.cfips, 0) for r in rows if _bit(r.cack, 0) == 1]
        else:
            fips = [r.pfips for r in rows if r.pack == 1]
        self.xfer_seen[i] = len(ext)
        # Stream 2: the even count of 8 to 64 beats fits the empty 32-entry pool, so the
        # pool takes every beat and the feed never stalls.
        all_taken = i != 2 or (done and len(ext) == len(sp.xfer_words))
        self.chk.ok(
            "EXT-XFER",
            len(ext) >= 1
            and ext == post
            and len(fips) >= 1
            and all(f == 1 for f in fips)
            and all_taken,
            stream=i,
            beats=len(sp.xfer_words),
            xfers=len(ext),
            post_mux=len(post),
            order_ok=int(ext == post),
            fips=int(bool(fips) and all(f == 1 for f in fips)),
            fips_words=len(fips),
            gap=sp.gap_pattern,
            ended_by_stall=int(not done),
        )

    async def _wait_pending(self, stream: int, transferred: int, bound: int) -> bool:
        """Wait until ``transferred`` beats completed and one beat is held on the port."""
        base = self.trace.ext_xfers[stream]
        n = await self._until(
            lambda: (
                self.trace.ext_xfers[stream] - base >= transferred and self.trace.stall[stream] >= 1
            ),
            bound,
        )
        return n is not None

    async def _strobe_leg(self, sp: StreamPlan) -> None:
        """CHK-EXT-STRB: a partial-strobe beat stays pending at the mux output for H
        clocks (and a pair with a partial second beat leaves fifo_level unchanged);
        after the TRNG reset and the source reset a 0xF beat completes."""
        i = sp.stream
        h = self.plan.hold
        await self._trng_reset()
        reason = ""
        # Control: a full-strobe beat (pair for stream 2) is accepted.
        if i == 2:
            lvl0, _ = await self._status_settled()
            self.ext.send(2, [sp.ctrl_word, sp.ctrl_word])
            ok = await self._settle_pairs(2, 2, SETTLE_CAP) is not None
            lvl1, _ = await self._status_settled()
            ctrl_delta = lvl1 - lvl0
            self.chk.ctrl("EXT-STRB", ok and ctrl_delta == 1, stream=2, ctrl_f_delta=ctrl_delta)
        else:
            self.ext.send(1, [sp.ctrl_word])
            ok = await self._settle_pairs(1, 1, SETTLE_CAP) is not None
            ctrl_delta = int(ok)
            self.chk.ctrl("EXT-STRB", ok, stream=1, ctrl_f_beat=int(ok))
            await self._trng_reset()
            lvl1 = 0
        # Error injection: a legal source beat with a partial strobe.
        open_graded_window(TEST, self.logger)
        if i == 2:
            self.ext.send(2, [sp.part_words[0]])
            self.ext.send(2, [sp.part_words[1]], strb=sp.strobe)
            held = await self._wait_pending(2, 1, SETTLE_CAP)
        else:
            self.ext.send(1, [sp.part_words[0]], strb=sp.strobe)
            held = await self._wait_pending(1, 0, SETTLE_CAP)
        self.trace.begin()
        await self._clocks(h)
        rows = self.trace.end()
        pending = held and all(r.pv[i] == 1 and r.pr[i] == 0 for r in rows) and len(rows) >= h
        pool_delta: int | str = "na"
        if i == 2:
            lvl2, _ = await self._status_settled()
            pool_delta = lvl2 - lvl1
        close_graded_window(self.logger)
        # Recovery: the sink reset and the source reset together, then a 0xF beat.
        await self._trng_reset(source_reset=i)
        words = [sp.recov_word, sp.recov_word] if i == 2 else [sp.recov_word]
        self.ext.send(i, words)
        post_ok = await self._settle_pairs(i, len(words), SETTLE_CAP) is not None
        if not held:
            reason = "partial_beat_not_held"
        fields = {
            "stream": i,
            "tstrb": f"0x{sp.strobe:x}",
            "pending": int(pending),
            "hold_clk": h,
            "pool_delta": pool_delta,
            "ctrl_f_delta": ctrl_delta,
            "source_reset": 1,
            "post_reset_f_beat": int(post_ok),
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("EXT-STRB", pending and pool_delta in (0, "na") and post_ok, **fields)

    async def _drop_leg(self, sp: StreamPlan) -> None:
        """CHK-EXT-DROP: with the select bit cleared every beat sees tready 1, no word
        reaches the post-mux probe and fifo_level does not change."""
        i = sp.stream
        sel = sp.s & ~sp.bit
        lvl0 = (await self._status_settled())[0] if i == 2 else 0
        open_graded_window(TEST, self.logger)
        got = await self._sel(sel)
        self.trace.begin()
        self.ext.send(i, sp.drop_words)
        done = await self._settle_pairs(i, len(sp.drop_words), 8 * len(sp.drop_words) + 200)
        await self._clocks(8)
        rows = self.trace.end()
        close_graded_window(self.logger)
        await self._drop_source(i)
        lvl1 = (await self._status_settled())[0] if i == 2 else 0
        tready_low = sum(1 for r in rows if _bit(r.er, i) != 1)
        post = post_xfers(rows, i)
        ctrl = self.xfer_seen.get(i, 0)
        self.chk.ctrl("EXT-DROP", ctrl >= 1, stream=i, ctrl_xfers=ctrl)
        self.chk.ok(
            "EXT-DROP",
            got == sel and done is not None and tready_low == 0 and not post and lvl1 == lvl0,
            stream=i,
            sel=f"0x{got:x}",
            sel_bit=(got >> i) & 1,
            tready_low=tready_low,
            post_mux_beats=len(post),
            pool_delta=lvl1 - lvl0 if i == 2 else "na",
            beats=len(sp.drop_words),
            ctrl_xfers=ctrl,
        )

    async def _bp_leg(self, sp: StreamPlan) -> None:
        """CHK-EXT-BP (stream 2): with the pool full tready falls with a beat pending;
        after the pops every pair appears once and in order."""
        h = self.plan.hold
        await self._sel(sp.s)
        await self._trng_reset()
        open_graded_window(TEST, self.logger)
        self.trace.begin()
        sent: list[int] = []
        stalled = False
        for a in sp.bp_pairs[:BP_PAIR_BOUND]:
            sent.append(a)
            self.ext.send(2, [a, a])
            if await self._settle_pairs(2, 2, SETTLE_CAP) is None:
                stalled = self.trace.stall[2] >= h
                break
        rows = self.trace.end()
        ncal = len(ext_xfers(rows, 2))
        tready_low = sum(1 for r in rows if _bit(r.ev, 2) == 1 and _bit(r.er, 2) == 0)
        level_at_stall, _ = await self._status_settled()
        pops: list[int] = []
        bad_resp = 0
        timeout = ""
        for _ in sent:
            lvl_ok = False
            for _ in range(STATUS_AGREE_READS):
                if pool_level(await self.pool.status()) >= 1:
                    lvl_ok = True
                    break
                await self._clocks(8)
            if not lvl_ok:
                timeout = "timeout:pool_level"
                break
            resp, data = await self._pop()
            bad_resp += int(resp != RESP_OKAY)
            pops.append(data)
        close_graded_window(self.logger)
        await self._drop_source(2)
        expect = [(a << 32) | a for a in sent]
        lost = sum(1 for e in expect if e not in pops)
        dup = len(pops) - len(set(pops))
        fields = {
            "stream": 2,
            "tready_low_cycles": tready_low,
            "level_at_stall": level_at_stall,
            "ncal": ncal,
            "pairs": len(sent),
            "lost": lost,
            "dup": dup,
            "order_ok": int(pops == expect),
            "bad_resp": bad_resp,
        }
        if not stalled:
            fields["reason"] = f"no_stall_within_bound={BP_PAIR_BOUND}"
        if timeout:
            fields["reason"] = timeout
        self.chk.ok(
            "EXT-BP",
            stalled and not timeout and level_at_stall == POOL_DEPTH and pops == expect
            and bad_resp == 0,
            **fields,
        )  # fmt: skip

    async def _ready_leg(self, sp: StreamPlan) -> None:
        """CHK-SEL-READY: for a selected stream 1 or 2 with no sink draining, tready
        falls with a beat pending; stream 2 accepts at least 64 beats first; for
        stream 1 an AES PRNG reseed after the fall completes the pending beat."""
        h = self.plan.hold
        await self._sel(sp.s)
        await self._trng_reset()
        graded = [j for j in (1, 2) if sp.s >> j & 1]
        open_graded_window(TEST, self.logger)
        self.trace.begin()
        for j in STREAMS:
            self.ext.send(j, sp.ready_words[j])
        bound = 4 * READY_BEAT_BOUND + SETTLE_CAP
        n = await self._until(lambda: all(self.trace.stall[j] >= h for j in graded), bound)
        rows = self.trace.end()
        rise: dict[int, int | str] = {j: "na" for j in graded}
        if 1 in graded and n is not None:
            base = self.trace.ext_xfers[1]
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
            r = await self._until(lambda: self.trace.ext_xfers[1] > base, TRNG_RESET_CAP)
            rise[1] = int(r is not None)
        close_graded_window(self.logger)
        s0 = [_bit(r.er, 0) for r in rows if _bit(r.ev, 0) == 1]
        self.chk.obs(
            "SEL-READY0",
            sel_bit=sp.s & 1,
            tvalid_clk=len(s0),
            tready_low_clk=sum(1 for v in s0 if v == 0),
        )
        await self._drop_source(*STREAMS)
        for j in graded:
            # The fall is the start of the stall that ends the leg: the last run of
            # clocks with tvalid 1 and tready 0 that reaches the end of the record and
            # lasts at least H clocks. Shorter stalls before it are the adapter staging
            # FIFO filling faster than the sink drains it.
            fall = _final_stall(rows, j, h)
            accepted = len(ext_xfers(rows[:fall] if fall is not None else rows, j))
            low = sum(1 for r in rows if _bit(r.ev, j) == 1 and _bit(r.er, j) == 0)
            first_ok = accepted >= 1
            self.chk.ctrl("SEL-READY", first_ok, stream=j, first_beat_accepted=int(first_ok))
            ok = n is not None and fall is not None and accepted < READY_BEAT_BOUND
            if j == 2:
                ok = ok and accepted >= 2 * POOL_DEPTH
            if j == 1:
                ok = ok and rise[1] == 1
            fields = {
                "stream": j,
                "sel_bit": 1,
                "tready_low_cycles": low,
                "accepted": accepted,
                "ncal": accepted,
                "final_stall_clk": len(rows) - fall if fall is not None else "na",
                "rise_after_drain": rise[j],
            }
            if n is None:
                fields["reason"] = f"no_fall_within_bound={READY_BEAT_BOUND}"
            self.chk.ok("SEL-READY", ok, **fields)

    async def _hold_leg(self, sp: StreamPlan) -> None:
        """CHK-SEL-HOLD: with the external source selected the filled internal endpoint
        holds tvalid 1, tready 0 and its word; after the reselect it delivers that word
        first. Control: with the internal source selected and a consumer active the
        endpoint drains."""
        i = sp.stream
        dut = cocotb.top
        # Bring-up of the internal chain; the bring-up writes the select itself.
        self.sb = await self.bring_up_entropy(strict=False, score_km="observe")
        sel_all = await self._sel(SEL_MASK)
        if i == 2:
            for _ in range(2 * POOL_DEPTH + 8):
                if pool_level(await self.pool.status()) == 0:
                    break
                await self._pop()
        reason = ""
        level0 = pool_level(await self.pool.status()) if i == 2 else 0
        n = await self._until(lambda: _bit(_known(dut.drbg_int_tvalid_o), i) == 1, SETTLE_CAP)
        open_graded_window(TEST, self.logger)
        changes = 0
        w = None
        held_ok = False
        if n is None:
            reason = f"timeout:endpoint_tvalid bound={SETTLE_CAP}"
        else:
            self.trace.begin()
            await self._clocks(sp.hold_win)
            rows = self.trace.end()
            w = _word(rows[0].idata, i) if rows else None
            changes = sum(1 for r in rows if _word(r.idata, i) != w)
            # An X or Z endpoint word reads None and fails the hold: None never matches.
            if w is None:
                reason = "unknown:endpoint_tdata"
            held_ok = (
                w is not None
                and bool(rows)
                and all(
                    _bit(r.iv, i) == 1 and _bit(r.ir, i) == 0 and _word(r.idata, i) == w
                    for r in rows
                )
            )
        # Reselect the internal source for the stream; a consumer is active.
        resel = SEL_MASK & ~sp.bit
        self.trace.begin()
        got = await self._sel(resel)
        if i == 1:
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
        await self._clocks(DRAIN_WINDOW)
        rows = self.trace.end()
        close_graded_window(self.logger)
        post = post_xfers(rows, i)
        first_ok = bool(post) and w is not None and post[0] is not None and post[0] == w
        if not reason and post and post[0] is None:
            reason = "unknown:post_mux_tdata"
        need = 1 if i == 1 else 2
        self.chk.ctrl("SEL-HOLD", len(post) >= need, stream=i, ctrl_drain_beats=len(post))
        fields = {
            "stream": i,
            "tvalid": int(held_ok),
            "tready": 0 if held_ok else "x",
            "tdata_changes": changes,
            "first_after_reselect==held": int(first_ok),
            "held": f"0x{w:08x}" if w is not None else "na",
            "ctrl_drain_beats": len(post),
            "hold_win": sp.hold_win,
            "sel_all": f"0x{sel_all:x}",
            "reselect": f"0x{got:x}",
            "pool_level_before_hold": level0 if i == 2 else "na",
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "SEL-HOLD",
            not reason and held_ok and changes == 0 and first_ok and sel_all == SEL_MASK
            and got == resel and level0 == 0,
            **fields,
        )  # fmt: skip
        self.sb.stop()
        self.sb = None

    async def _pop_leg(self, sp: StreamPlan) -> None:
        """CHK-POOL-DATA: each pop answers OKAY with the next pair in order, and the
        settled fifo_level equals the model level min(32, completed pairs - pops)."""
        h = self.plan.hold
        await self._trng_reset()
        got = await self._sel(sp.pop_sel)
        self.chk.ctrl("POOL-DATA", got == sp.pop_sel, sel=f"0x{got:x}")
        open_graded_window(TEST, self.logger)
        sent: list[int] = []
        completed = 0
        pops = 0
        # Counter value of port 2 at the offer of a pair that stays pending at level 32.
        pend_base: int | None = None
        for a in sp.fill_pairs:
            sent.append(a)
            self.ext.send(2, [a, a])
            if await self._settle_pairs(2, 2, SETTLE_CAP) is not None:
                completed += 1
        lvl, _ = await self._status_settled()
        expect = min(POOL_DEPTH, completed - pops)
        self.chk.ok(
            "POOL-DATA", lvl == expect, op="fill", level_after=lvl, expect_level=expect,
            pairs=len(sent),
        )  # fmt: skip
        feeds = list(sp.feed_pairs)
        # Corner run: feeds to model level 32, one feed offered at level 32, then a pop.
        corner = ["feed"] * (POOL_DEPTH - expect) + ["feed_full", "pop"]
        for k, op in enumerate(corner + list(sp.ops)):
            model = min(POOL_DEPTH, completed - pops)
            if op == "pop" and model == 0:
                op = "status"
            if op == "feed" and model == POOL_DEPTH and k >= len(corner):
                op = "status"
            fields: dict = {"op": op, "level_before": model}
            ok = True
            if op in ("feed", "feed_full"):
                a = feeds.pop(0)
                sent.append(a)
                base = self.trace.ext_xfers[2]
                self.ext.send(2, [a, a])
                if await self._settle_pairs(2, 2, SETTLE_CAP) is not None:
                    completed += 1
                elif op == "feed_full" and self.trace.stall[2] >= h:
                    pend_base = base
                else:
                    ok = False
                    fields["reason"] = f"timeout:feed bound={SETTLE_CAP}"
            elif op == "pop":
                resp, data = await self._pop()
                want = (sent[pops] << 32) | sent[pops]
                pops += 1
                if pend_base is not None:
                    left = 2 - (self.trace.ext_xfers[2] - pend_base)
                    if left <= 0 or await self._settle_pairs(2, left, SETTLE_CAP) is not None:
                        completed += 1
                        pend_base = None
                ok = resp == RESP_OKAY and data == want
                fields.update(pop=pops, resp=resp, data=f"0x{data:016x}", expect=f"0x{want:016x}")
            lvl, _ = await self._status_settled()
            expect = min(POOL_DEPTH, completed - pops)
            fields.update(level_after=lvl, expect_level=expect, pending=int(pend_base is not None))
            self.chk.ok("POOL-DATA", ok and lvl == expect, **fields)
            if "reason" in fields:
                break
        close_graded_window(self.logger)
        await self._drop_source(2)

    # --- legs after both streams -------------------------------------------------------
    async def _irq_leg(self) -> None:
        """CHK-EXT-IRQ: ext_trng_irq_i = 1 gives vector bit 16 = 1, and 0 gives 0. Each level
        is held for IRQ_HOLD clocks after bit 16 follows it (``OBS-EXT-IRQ-HOLD``)."""
        dut = cocotb.top
        vec = dut.sep_internal_interrupts_probe_o
        mask = 1 << VEC_EXT_IRQ

        def bit16() -> int:
            return (self.rd(vec, mask) >> VEC_EXT_IRQ) & 1

        before = bit16()
        self.chk.ctrl("EXT-IRQ", before == 0, vec16_before=before)
        open_graded_window(TEST, self.logger)
        for level in (1, 0):
            self.ext.set_irq(level)
            n = await self._until(lambda lv=level: bit16() == lv, IRQ_BOUND)
            fields = {"irq_i": level, "vec16": bit16(), "clk": n if n is not None else "na"}
            if n is None:
                fields["reason"] = f"timeout:vec16 bound={IRQ_BOUND}"
            self.chk.ok("EXT-IRQ", n is not None, **fields)
            # The input keeps the level for IRQ_HOLD clocks after bit 16 follows it, so the
            # sampled clock after the change sees the input and bit 16 at the same level.
            # Whether bit 16 is a level is not stated, so the hold is logged only.
            if n is not None:
                held = 0
                for _ in range(IRQ_HOLD):
                    await RisingEdge(cocotb.top.clk_i)
                    held += int(bit16() == level)
                self.chk.obs("EXT-IRQ-HOLD", irq_i=level, vec16_at_level_clk=held, hold=IRQ_HOLD)
        close_graded_window(self.logger)

    async def _lock(self, value: int) -> int:
        await self.reg._wr(LOCK_ADDR, value)
        return await self.reg._rd(LOCK_ADDR) & LOCK_MASK

    async def _lock_leg(self) -> None:
        """CHK-SEL-LOCK: after the lock write of 1, a write of 0 leaves it at 1, a
        select write leaves the old value, and a TRNG reset leaves the lock at 1."""
        plan = self.plan
        open_graded_window(TEST, self.logger)
        pre = await self._sel(plan.a)
        self.chk.ctrl("SEL-LOCK", pre == plan.a, pre_lock_sel=f"0x{pre:x}")
        await self._clocks(plan.idle_gap)
        lock1 = await self._lock(LOCK_MASK)
        lock0 = await self._lock(0)
        kept = await self._sel(plan.b)
        await self._trng_reset()
        lock_r = await self.reg._rd(LOCK_ADDR) & LOCK_MASK
        sel_r = await self.reg._rd(SEL_ADDR) & SEL_MASK
        self.pre_global = (lock_r, sel_r)
        self.chk.ok(
            "SEL-LOCK",
            lock1 == LOCK_MASK and lock0 == LOCK_MASK and kept == plan.a
            and lock_r == LOCK_MASK and sel_r == plan.a,
            lock=lock1, write0_lock=lock0, sel_kept=f"0x{kept:x}", tried=f"0x{plan.b:x}",
            after_trng_reset_lock=lock_r, ctrl_sel=f"0x{sel_r:x}", pre_lock_sel=f"0x{pre:x}",
        )  # fmt: skip

    async def _global_reset(self) -> None:
        await self.pulse_rst_ni()
        self.swrst.value = SW_RESET_N_RESET_DEFAULT

    async def _global_leg(self) -> None:
        """CHK-SEL-GLOBAL: after a rst_ni pulse the lock is 0 and the select is 0x7."""
        pre_lock, pre_sel = self.pre_global
        self.chk.ctrl(
            "SEL-GLOBAL",
            pre_lock == LOCK_MASK and pre_sel != SEL_RESET,
            pre_lock=pre_lock,
            pre_sel=f"0x{pre_sel:x}",
        )
        # The window stays open across the global reset (the graded stimulus).
        await self._global_reset()
        lock = await self.reg._rd(LOCK_ADDR) & LOCK_MASK
        sel = await self.reg._rd(SEL_ADDR) & SEL_MASK
        close_graded_window(self.logger)
        self.chk.ok(
            "SEL-GLOBAL",
            lock == 0 and sel == SEL_RESET,
            lock=lock,
            sel=f"0x{sel:x}",
            pre_lock=pre_lock,
            pre_sel=f"0x{pre_sel:x}",
        )

    async def _lockfirst_leg(self) -> None:
        """CHK-SEL-LOCKFIRST: with the lock set before any select write, a select write
        leaves the select at 0x7. Control: after a rst_ni pulse a select write lands."""
        open_graded_window(TEST, self.logger)
        lock = await self._lock(LOCK_MASK)
        sel = await self._sel(0)
        close_graded_window(self.logger)
        await self._global_reset()
        lock_after = await self.reg._rd(LOCK_ADDR) & LOCK_MASK
        lands = await self._sel(0)
        ctrl = lock_after == 0 and lands == 0
        self.chk.ctrl("SEL-LOCKFIRST", ctrl, ctrl_after_reset_write_lands=int(ctrl))
        self.chk.ok(
            "SEL-LOCKFIRST",
            lock == LOCK_MASK and sel == SEL_RESET,
            lock=lock,
            write="0x0",
            sel=f"0x{sel:x}",
            ctrl_after_reset_write_lands=int(ctrl),
        )
