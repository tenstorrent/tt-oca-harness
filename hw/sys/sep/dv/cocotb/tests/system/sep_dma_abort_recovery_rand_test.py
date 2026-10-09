# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA ABORT at a drawn phase, the quiet bus after it and a clean recovery copy.

The DMA abort contract (``secure_dma.adoc``, CONTROL.ABORT, STATUS.ABORTED):
a write of CONTROL.ABORT during a transfer sets STATUS.ABORTED once the
aborted operation drains, and no DMA request beat follows the ABORTED rise.
ABORTED clears by write-one-to-clear. A copy after the abort, with no reset,
completes with the right data (``sep-programming.adoc``, DMA).

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense with a PROD image
and zero disable vectors, because the leaf pulses ``rst_ni``. Every abort run
starts from a cold reset; the recovery copy of a run follows with no reset.

Randomization (``SepSeededRng`` from the run seed): chunk size C (1024 to 4096
bytes), chunk count n (2 or more, T = n * C from 4 KiB to 16 KiB), the phase
class of abort run 2 (first transaction, chunk boundary or final transaction;
run 1 is always mid chunk), the abort point inside the class, the source and
destination offsets and guards in the SEP SRAM, the sentinel byte, the source
words and the recovery copy shapes. The reference copy measures its clean time
t_clean (clocks from the end of the first GO write to the STATUS read that
first shows DONE=1, re-GO gaps included). t_clean sets the abort delay only;
it is never an expected value.

Abort-run repeats (no grade from a repeated run, each from a cold reset):

* ``busy_at_abort`` = 0 (``dma_busy_probe_o`` on the clock in which the W beat
  of the ABORT write completes on ``s_axi``): ``OBS-DMA-ABORT-REDRAW`` case
  ``not_started`` (larger delay) or ``ended`` (smaller delay); at most
  ``MAX_REDRAW`` repeats, then ``CTRL-MISSING``. Each change is
  t_clean / (10 n), never below 0.
* final-transaction or chunk-boundary class, and the wait ends with DONE or
  CHUNK_DONE, BUSY=0 and ABORTED=0: case ``finished`` (smaller delay), same
  bound.
* the AR beat count k at that W beat is outside the window of the class
  (``OBS-DMA-ABORT-LANDING``): repeat with the delay moved by (target - k)
  times t_clean / N, never below 0; at most ``MAX_LANDING`` repeats, then
  ``CTRL-MISSING``. Windows, with M = C / 4 transactions per chunk, N = T / 4
  and W = max(4, M / 20): first transaction 1 <= k <= W; mid chunk
  W < k < M - W; chunk boundary |k - j * M| <= W; final transaction
  N - N / 10 <= k <= N.

Checkers:
  CHK-DMA-ABORT        with busy_at_abort = 1, ABORTED reads 1 within the
                       bounded wait; ABORTED read 0 before the GO write.
  CHK-DMA-ABORT-QUIET  the destination and guard image read after ABORTED
                       equals the image read again t_clean clocks later.
                       Seed control: one graded run left both a written and a
                       sentinel destination word (``CTRL-MISSING`` otherwise).
  CHK-DMA-ABORT-BEATS  no AR or AW handshake on ``dma_axi_req_probe_o`` from
                       the ABORTED rise on ``dma_status_probe_o`` to the GO
                       write of the recovery copy; beats appear before the
                       ABORT write and after the recovery GO write.
  CHK-DMA-ABORT-CLR    a write of 1 to STATUS.ABORTED clears it.
  CHK-DMA-RECOVER      the recovery copy sets DONE, leaves ERROR and
                       ERROR_CODE clear, copies the data and leaves the guards
                       and the rest of the destination at the sentinel.

Logged only: ``OBS-DMA-ABORT`` (BUSY, GO, DONE and ERROR after the abort, which
the register description does not state) and the destination content after the
abort.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_dma_model import DmaXfer, bytes_to_words, words_to_bytes
from env.sep_dma_model import draw_source_words as _draw_words
from env.sep_dma_tap import SepDmaTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_lcc_golden import LC_PROD
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_dma_ops import (
    _D,
    CONTROL,
    ERROR_CODE,
    ERROR_CODE_MASK,
    ST_ABORTED,
    ST_CHUNK_DONE,
    SepDmaOps,
    SepMemWords,
    control_word,
)

TEST = "sep_dma_abort_recovery_rand_test"

# SEP SRAM (memory_map.adoc): the DMA enabled range and the home of every buffer.
SRAM_BASE = 0x1000_0000
SRAM_LIMIT = 0x1003_FFFF
SRAM_SIZE = SRAM_LIMIT - SRAM_BASE + 1
ASID_SEP = 0x77

MAX_REDRAW = 8
MAX_LANDING = 8
ABORT_POLL_BOUND = 400
BUSY_RISE_BOUND = 2_000
POLL_PER_KIB = 1_500
CLASSES_RUN2 = ("first", "boundary", "final")

CTRL_GO_MASK = _D.field_mask("CONTROL", "go")


def _word(b: int) -> int:
    return b * 0x0101_0101


@dataclass
class _RunPlan:
    idx: int
    cls: str
    j: int = 0
    rec_chunk: int = 0
    rec_total: int = 0
    rec_words: list[int] | None = None


@dataclass
class _Attempt:
    outcome: str  # graded | not_started | ended | finished | landing_low | landing_high
    d: int
    k: int
    busy_at_abort: int


class _Cfg:
    """Seed-drawn plan of the leaf."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.chunk = 4 * rng.randrange(256, 1025)
        n_lo = max(2, -(-4096 // self.chunk))
        n_hi = 16384 // self.chunk
        self.n = rng.randrange(n_lo, n_hi + 1)
        self.total = self.n * self.chunk
        self.guard = 4 * rng.randrange(1, 17)
        self.run2_cls = rng.choice(CLASSES_RUN2)
        # Abort points in per-mille of the class base (stimulus only).
        self.mid_pm = rng.randrange(250, 751)
        self.bnd_j = rng.randrange(1, self.n)
        self.bnd_pm = rng.randrange(-50, 51)
        self.fin_pm = rng.randrange(900, 991)
        # Placement: two footprints of T + 2 guards, in a drawn order and gap.
        span = self.total + 2 * self.guard
        self.src_first = bool(rng.getrandbits(1))
        gap = 4 * rng.randrange(0, 1025)
        start = 4 * rng.randrange(0, (SRAM_SIZE - 2 * span - gap) // 4 + 1)
        lo = SRAM_BASE + start + self.guard
        hi = SRAM_BASE + start + span + gap + self.guard
        self.src, self.dst = (lo, hi) if self.src_first else (hi, lo)
        # Data: the sentinel byte first, then source words that never hold it.
        self.sentinel = rng.randrange(256)
        self.src_words = _draw_words(rng, self.total // 4, self.sentinel)
        self.runs = [_RunPlan(1, "mid"), _RunPlan(2, self.run2_cls)]
        for r in self.runs:
            r.rec_chunk = 4 * rng.randrange(16, 257)
            r.rec_total = r.rec_chunk * rng.randrange(1, 4)
            r.rec_words = _draw_words(rng, r.rec_total // 4, self.sentinel)
        for a, b in ((self.src, self.dst), (self.dst, self.src)):
            assert a - self.guard >= SRAM_BASE and a + self.total + self.guard - 1 <= SRAM_LIMIT
            assert a + self.total + self.guard <= b - self.guard or b + self.total <= a
        self.m_txn = self.chunk // 4
        self.n_txn = self.total // 4
        self.w_txn = max(4, self.m_txn // 20)

    def draw_line(self) -> str:
        return (
            f"seed={self.seed} chunk={self.chunk} n={self.n} total={self.total} "
            f"src=0x{self.src:08x} dst=0x{self.dst:08x} guard={self.guard} "
            f"src_first={int(self.src_first)} sentinel=0x{self.sentinel:02x} "
            f"run2_class={self.run2_cls} mid_pm={self.mid_pm} bnd_j={self.bnd_j} "
            f"bnd_pm={self.bnd_pm} fin_pm={self.fin_pm} "
            + " ".join(f"rec{r.idx}={r.rec_total}/{r.rec_chunk}" for r in self.runs)
        )

    def window(self, cls: str, j: int) -> tuple[int, int]:
        """Inclusive AR-beat window of a phase class at the ABORT write."""
        m, w, n = self.m_txn, self.w_txn, self.n_txn
        if cls == "first":
            return 1, w
        if cls == "mid":
            return w + 1, m - w - 1
        if cls == "boundary":
            return j * m - w, j * m + w
        return n - n // 10, n

    def target(self, cls: str, j: int) -> int:
        """AR-beat count that a landing repeat aims at inside the class window."""
        m, w, n = self.m_txn, self.w_txn, self.n_txn
        return {
            "first": max(1, w // 2),
            "mid": m // 2,
            "boundary": j * m - w // 2,
            "final": n - n // 20,
        }[cls]


@pyuvm.test()
class sep_dma_abort_recovery_rand_test(sep_base_test):
    """ABORT during a transfer, the quiet bus after ABORTED and a recovery copy."""

    required_evidence = (
        "CHK-DMA-ABORT",
        "CHK-DMA-ABORT-QUIET",
        "CHK-DMA-ABORT-BEATS",
        "CHK-DMA-ABORT-CLR",
        "CHK-DMA-RECOVER",
    )

    # ---- helpers -----------------------------------------------------------
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.cfg_t.seed, line)
        self.n_checks += 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.cfg_t.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, line: str) -> None:
        msg = f"CTRL-MISSING seed={self.cfg_t.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    @property
    def clk(self) -> int:
        return self.busy.clk

    async def _cold_reset(self) -> None:
        close_graded_window(self.logger)
        await self.pulse_rst_ni()

    async def _setup_copy(self, src_words: list[int]) -> None:
        """Range, ASID, source, sentinel destination and guards, transfer registers."""
        c = self.cfg_t
        ops = self.ops
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)
        await ops.wr(_D.addr("ADDR_SPACE_ID"), ASID_SEP)
        await self.mem.fill(c.src, src_words)
        await self._fill_dst_sentinel()
        await ops.program_transfer(src=c.src, dst=c.dst, total=c.total, chunk=c.chunk)

    async def _fill_dst_sentinel(self) -> None:
        c = self.cfg_t
        n = (c.total + 2 * c.guard) // 4
        await self.mem.fill(c.dst - c.guard, [_word(c.sentinel)] * n)

    async def _read_dst_image(self) -> list[int]:
        c = self.cfg_t
        return await self.mem.read(c.dst - c.guard, (c.total + 2 * c.guard) // 4)

    # ---- reference copy ----------------------------------------------------
    async def _reference(self) -> None:
        c = self.cfg_t
        await self._cold_reset()
        await self._setup_copy(c.src_words)
        t_rd0 = self.clk
        await self.ops.read_status()
        self.read_cost = max(1, self.clk - t_rd0)
        await self.ops.go(initial=1)
        t0 = self.clk
        res = await self.ops.run_to_done(
            c.total, busy=self.busy, w1c_chunk_done=True, busy_bound=BUSY_RISE_BOUND, tag=" ref"
        )
        self.t_clean = self.clk - t0
        img = await self.mem.read(c.dst, c.total // 4)
        bad = sum(1 for a, b in zip(img, c.src_words) if a != b)
        line = (
            f"t_clean={self.t_clean} go_writes={res.go_writes} polls={res.polls} "
            f"read_cost={self.read_cost} {res.status.fmt()} mismatch_words={bad}"
        )
        self.logger.info("REF-COPY LOG seed=%d %s", c.seed, line)
        if not (res.status.done and not res.status.error and bad == 0):
            self._ctrl_missing(f"reference copy did not complete clean: {line}")
        self.step = max(1, self.t_clean // (10 * c.n))

    def _initial_delay(self, plan: _RunPlan) -> int:
        c = self.cfg_t
        share = self.t_clean // c.n
        if plan.cls == "mid":
            return share * c.mid_pm // 1000
        if plan.cls == "first":
            return 0
        if plan.cls == "boundary":
            plan.j = c.bnd_j
            return max(0, c.bnd_j * share + share * c.bnd_pm // 1000)
        return self.t_clean * c.fin_pm // 1000

    # ---- one abort attempt -------------------------------------------------
    async def _delay_with_rego(self, t0: int, d: int) -> int:
        """Run the delay ``d`` from clock ``t0``, applying the re-GO rule; return GO writes."""
        ops = self.ops
        go_writes = 1
        while self.clk - t0 < d:
            if d - (self.clk - t0) > 2 * self.read_cost:
                st = await ops.read_status()
                if st.chunk_done and not st.done and not st.busy:
                    await ops.wr(_D.addr("STATUS"), ST_CHUNK_DONE)
                    m = self.busy.mark()
                    await ops.wr(CONTROL, control_word(go=1))
                    go_writes += 1
                    await self.busy.wait_rise(m, BUSY_RISE_BOUND)
            else:
                await RisingEdge(cocotb.top.clk_i)
        return go_writes

    async def _abort_w_handshake(self, out: dict) -> None:
        """Record ``dma_busy_probe_o`` and a tap mark on the clock of the ABORT W handshake.

        In the read-only phase after edge t, VALID and READY high mean the beat
        transfers at edge t + 1, and the BUSY level is the value it holds into
        that edge: the level on the clock in which the ABORT write completes on
        ``s_axi``.
        """
        top = cocotb.top
        while True:
            await RisingEdge(top.clk_i)
            await ReadOnly()
            if self.rd(top.s_axi_wvalid) and self.rd(top.s_axi_wready):
                out["busy"] = self.rd(top.dma_busy_probe_o)
                out["clk"] = self.clk
                out["mark"] = self.tap.mark()
                return

    async def _attempt(self, plan: _RunPlan, d: int, rec: dict) -> _Attempt:
        c = self.cfg_t
        ops = self.ops
        await self._cold_reset()
        await self._setup_copy(c.src_words)
        st0 = await ops.read_status()
        rec["aborted_before"] = st0.aborted
        if st0.aborted:
            self._ctrl_missing(f"run={plan.idx} ABORTED reads 1 before GO: {st0.fmt()}")

        open_graded_window(TEST, self.logger)
        m_tap_go = self.tap.mark()
        m_busy_go = self.busy.mark()
        await ops.go(initial=1)
        t0 = self.clk
        go_writes = await self._delay_with_rego(t0, d)
        t_ab0 = self.clk
        w_hs: dict = {}
        watch = cocotb.start_soon(self._abort_w_handshake(w_hs))
        await ops.abort()
        t_ab1 = self.clk
        if "busy" not in w_hs:
            watch.cancel()
            self._ctrl_missing(f"run={plan.idx} no W handshake of the ABORT write on s_axi")
        busy_at_abort = w_hs["busy"]
        k = len(self.tap.between(m_tap_go, w_hs["mark"]).ar)
        lo, hi = c.window(plan.cls, plan.j)
        self.logger.info(
            "ABORT-WRITE LOG seed=%d run=%d phase=%s d=%d go_writes=%d write_clks=%d..%d "
            "w_handshake_clk=%d busy_at_abort=%d busy_at_return=%s ar_beats=%d window=%d..%d",
            c.seed,
            plan.idx,
            plan.cls,
            d,
            go_writes,
            t_ab0 - t0,
            t_ab1 - t0,
            w_hs["clk"] - t0,
            busy_at_abort,
            self.busy.level(),
            k,
            lo,
            hi,
        )
        if not busy_at_abort:
            case = "ended" if self.busy.rose_since(m_busy_go) else "not_started"
            return _Attempt(case, d, k, 0)
        if k < lo:
            return _Attempt("landing_low", d, k, 1)
        if k > hi:
            return _Attempt("landing_high", d, k, 1)

        # Wait for ABORTED, or for a chunk or transfer that finished first.
        st = None
        for _ in range(ABORT_POLL_BOUND):
            st = await ops.read_status()
            if st.aborted:
                break
            if not st.busy and (st.done or st.chunk_done):
                await ClockCycles(cocotb.top.clk_i, 16)
                st = await ops.read_status()
                break
        assert st is not None
        if not st.aborted:
            finished = not st.busy and (st.done or st.chunk_done)
            if finished and plan.cls in ("final", "boundary"):
                return _Attempt("finished", d, k, 1)
            self._fail(
                "CHK-DMA-ABORT",
                f"phase={plan.cls} busy_at_abort=1 aborted=0 aborted_before=0 "
                f"bound={ABORT_POLL_BOUND} {st.fmt()}",
            )
        rec.update(m_tap_go=m_tap_go, m_tap_ab=w_hs["mark"], k=k, d=d)
        return _Attempt("graded", d, k, 1)

    # ---- one graded run ------------------------------------------------------
    async def _abort_run(self, plan: _RunPlan) -> dict:
        c = self.cfg_t
        ops = self.ops
        d = self._initial_delay(plan)
        redraws = landing = 0
        rec: dict = {}
        while True:
            att = await self._attempt(plan, d, rec)
            if att.outcome == "graded":
                break
            if att.outcome.startswith("landing"):
                landing += 1
                self.logger.info(
                    "OBS-DMA-ABORT-LANDING seed=%d phase=%s ar_beats=%d window=%d..%d d=%d "
                    "repeat=%d",
                    c.seed,
                    plan.cls,
                    att.k,
                    *c.window(plan.cls, plan.j),
                    d,
                    landing,
                )
                if landing > MAX_LANDING:
                    self._ctrl_missing(
                        f"run={plan.idx} phase={plan.cls}: no landing in the class window "
                        f"after {MAX_LANDING} repeats"
                    )
                # A landing repeat moves the delay by the beat error times the
                # clean clocks per transaction, toward the target of the class.
                cpt = max(1, self.t_clean // c.n_txn)
                d = max(0, d + (c.target(plan.cls, plan.j) - att.k) * cpt)
                continue
            redraws += 1
            self.logger.info(
                "OBS-DMA-ABORT-REDRAW seed=%d phase=%s busy_at_abort=%d case=%s d=%d",
                c.seed,
                plan.cls,
                att.busy_at_abort,
                att.outcome,
                d,
            )
            if redraws > MAX_REDRAW:
                self._ctrl_missing(
                    f"run={plan.idx} phase={plan.cls}: no graded abort after {MAX_REDRAW} repeats"
                )
            d = d + self.step if att.outcome == "not_started" else max(0, d - self.step)

        # Step 8: OBS-DMA-ABORT.
        st = await ops.read_status()
        ctl = await ops.rd(CONTROL)
        self.logger.info(
            "OBS-DMA-ABORT seed=%d busy=%d go=%d done=%d error=%d",
            c.seed,
            st.busy,
            int(bool(ctl & CTRL_GO_MASK)),
            st.done,
            st.error,
        )
        # Step 9: images.
        img1 = await self._read_dst_image()
        await ClockCycles(cocotb.top.clk_i, self.t_clean)
        img2 = await self._read_dst_image()
        g = c.guard // 4
        dest1 = img1[g : g + c.total // 4]
        sw = _word(c.sentinel)
        n_written = sum(1 for x in dest1 if x != sw)
        n_sent = len(dest1) - n_written
        diff = [i for i, (a, b) in enumerate(zip(img1, img2)) if a != b]
        rec.update(quiet_ok=not diff, quiet_diff=diff[:4], written=n_written, sentinel=n_sent)
        # Step 10: ABORTED W1C.
        st_b = await ops.read_status()
        await ops.wr(_D.addr("STATUS"), ST_ABORTED)
        st_a = await ops.read_status()
        fc_b = field_compare(st_b.raw, ST_ABORTED, ST_ABORTED)
        fc_a = field_compare(st_a.raw, 0, ST_ABORTED)
        clr_line = (
            f"aborted_before_w1c={st_b.aborted} aborted_after_w1c={st_a.aborted} "
            f"before[{fc_b.fields()}] after[{fc_a.fields()}]"
        )
        if not fc_b.ok:
            self._ctrl_missing(f"CHK-DMA-ABORT-CLR control: ABORTED not 1 before W1C: {clr_line}")
        # Step 11: recovery copy, no reset.
        await ops.clean_state()
        await ops.wr(CONTROL, control_word())
        await self.mem.fill(c.src, plan.rec_words)
        await self._fill_dst_sentinel()
        await ops.program_transfer(src=c.src, dst=c.dst, total=plan.rec_total, chunk=plan.rec_chunk)
        m_tap_rec = self.tap.mark()
        await ops.go(initial=1)
        res = await ops.run_to_done(
            plan.rec_total,
            busy=self.busy,
            w1c_chunk_done=True,
            busy_bound=BUSY_RISE_BOUND,
            tag=" recovery",
        )
        ecode = await ops.rd(ERROR_CODE)
        img_r = await self._read_dst_image()
        await ClockCycles(cocotb.top.clk_i, 8)
        ev_go = self.tap.since(rec["m_tap_go"])
        ev_rec = self.tap.since(m_tap_rec)
        close_graded_window(self.logger)

        # Model image of the recovery copy over the sentinel destination and guards.
        x = DmaXfer(c.src, c.dst, plan.rec_total, plan.rec_chunk)
        init = words_to_bytes(c.dst - c.guard, [sw] * len(img_r))
        want = bytes_to_words(
            x.dst_image(words_to_bytes(c.src, plan.rec_words), init), c.dst - c.guard, len(img_r)
        )
        n_rec = plan.rec_total // 4
        mem_bad = sum(1 for i in range(n_rec) if img_r[g + i] != want[g + i])
        guard_idx = [i for i in range(len(img_r)) if not g <= i < g + n_rec]
        guard_bad = sum(1 for i in guard_idx if img_r[i] != want[i])

        # CHK-DMA-ABORT (the run reached ABORTED=1 in _attempt).
        self._pass(
            "CHK-DMA-ABORT",
            f"phase={plan.cls} busy_at_abort=1 aborted=1 aborted_before={rec['aborted_before']} "
            f"dest_words_written={n_written} redraws={redraws} landing_repeats={landing} "
            f"d={rec['d']} ar_beats_at_abort={rec['k']}",
        )
        # CHK-DMA-ABORT-CLR.
        if not fc_a.ok:
            self._fail("CHK-DMA-ABORT-CLR", clr_line)
        self._pass("CHK-DMA-ABORT-CLR", clr_line)
        # CHK-DMA-ABORT-BEATS.
        rises = [t for t in ev_go.rises("aborted") if t >= rec["m_tap_ab"].clk]
        ev_pre = self.tap.between(rec["m_tap_go"], rec["m_tap_ab"])
        before = ev_pre.ar + ev_pre.aw
        if not rises:
            self._fail(
                "CHK-DMA-ABORT-BEATS",
                f"phase={plan.cls} no ABORTED rise on dma_status_probe_o after the ABORT write",
            )
        t_rise = rises[0]
        after = [b for b in ev_go.ar + ev_go.aw if t_rise <= b.clk < m_tap_rec.clk]
        n_rec_beats = len(ev_rec.ar) + len(ev_rec.aw)
        last_drain = max(
            [b.clk for b in ev_go.ar + ev_go.aw + ev_go.w + ev_go.b if b.clk < t_rise],
            default=None,
        )
        beats_line = (
            f"phase={plan.cls} beats_before_abort={len(before)} beats_after_aborted={len(after)} "
            f"beats_recovery={n_rec_beats} aborted_rise_clk={t_rise} abort_write_clk="
            f"{rec['m_tap_ab'].clk} last_beat_before_rise={last_drain} "
            f"w_after={sum(1 for b in ev_go.w if t_rise <= b.clk < m_tap_rec.clk)} "
            f"b_after={sum(1 for b in ev_go.b if t_rise <= b.clk < m_tap_rec.clk)}"
        )
        if not before or n_rec_beats == 0:
            self._ctrl_missing(f"CHK-DMA-ABORT-BEATS control: {beats_line}")
        if after:
            b0 = after[0]
            self._fail(
                "CHK-DMA-ABORT-BEATS",
                beats_line + f" first_after={b0.ch}@{b0.clk} addr=0x{b0.addr or 0:08x}",
            )
        self._pass("CHK-DMA-ABORT-BEATS", beats_line)
        # CHK-DMA-RECOVER.
        fc_e = field_compare(ecode, 0, ERROR_CODE_MASK)
        rec_line = (
            f"reset_between=0 done={res.status.done} error={res.status.error} "
            f"mem_mismatch={mem_bad} guard_ok={int(guard_bad == 0)} go_writes={res.go_writes} "
            f"error_code[{fc_e.fields()}]"
        )
        if not (
            res.status.done and not res.status.error and fc_e.ok and mem_bad == 0 and guard_bad == 0
        ):
            self._fail("CHK-DMA-RECOVER", rec_line)
        self._pass("CHK-DMA-RECOVER", rec_line)
        return rec

    # ---- scenario ----------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.cfg_t = c = _Cfg(seed)
        self.n_checks = 0
        self.logger.info(
            "PLAN seed=%d reference copy, abort run 1 (mid), abort run 2 (%s), each with a "
            "recovery copy; repeats <= %d (redraw) and <= %d (landing) per run",
            seed,
            c.run2_cls,
            MAX_REDRAW,
            MAX_LANDING,
        )
        self.logger.info("DRAW %s", c.draw_line())

        image = self.select_efuse_image(lc_raw=LC_PROD, fixed={"SIP_DIS": 0, "SYS_DIS": 0})
        self.write_efuse_image(image)
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.ops = SepDmaOps(self)
        # One STATUS read takes fewer clocks than the DMA needs per KiB at width 4,
        # so the wait for DONE allows more reads per KiB than the helper default.
        self.ops.POLL_PER_KIB = POLL_PER_KIB
        self.mem = SepMemWords(self)
        self.busy = SepBitWatch(cocotb.top.dma_busy_probe_o, {"busy": 0}).start()
        self.tap = SepDmaTap().start()
        await ClockCycles(cocotb.top.clk_i, 2)

        await self._reference()
        self.logger.info("DRAW seed=%d t_clean=%d step=%d", seed, self.t_clean, self.step)
        recs = []
        for plan in c.runs:
            recs.append(await self._abort_run(plan))
        close_graded_window(self.logger)

        ctrl = next((r for r in recs if r["written"] >= 1 and r["sentinel"] >= 1), None)
        if ctrl is None:
            self._ctrl_missing(
                "no graded abort run left both a written and a sentinel destination word: "
                + " ".join(f"run{i + 1}={r['written']}/{r['sentinel']}" for i, r in enumerate(recs))
            )
        for i, r in enumerate(recs):
            line = (
                f"image_after_aborted_eq_image_later={int(r['quiet_ok'])} "
                f"control_nonsentinel_words={ctrl['written']} "
                f"control_sentinel_words={ctrl['sentinel']} run={i + 1} "
                f"run_written={r['written']} run_sentinel={r['sentinel']}"
            )
            if not r["quiet_ok"]:
                self._fail("CHK-DMA-ABORT-QUIET", line + f" first_diff_idx={r['quiet_diff']}")
            self._pass("CHK-DMA-ABORT-QUIET", line)

        await self.tap.stop()
        await self.busy.stop()
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, seed, self.n_checks)
