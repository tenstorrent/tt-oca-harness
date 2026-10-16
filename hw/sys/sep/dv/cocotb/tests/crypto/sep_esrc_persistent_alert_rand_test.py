# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC persistent-failure threshold: trip, no trip, gap, disable, halt and exit.

Contract (``hw/ip/entropy_source/doc/architecture.adoc:136`` and ``:138``;
``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc:71``, ``:140``,
``:209``, ``:409``, ``:411``, ``:728``, ``:762``):
  * ``ALERT_SUMMARY_FAIL_COUNTS.ANY_FAIL_COUNT`` counts consecutive failing
    health-test windows. When it reaches ``ALERT_THRESHOLD.THRESHOLD`` (reset
    0x4) the main state machine enters AlertHang: ``MAIN_SM_STATUS.ALERT`` and
    ``INTR_STATUS.PERSISTENT_FAILURE`` set and the entropy output halts.
  * A threshold of 0 disables the comparator; the counter keeps counting.
  * AlertHang lasts until a reset or until ``CTRL.MODULE_ENABLE`` is cleared.
    A write of one clears the sticky bits and does not resume the output.
  * The TRNG reset is a full-IP reset (``architecture.adoc:223``), so
    ``ALERT_THRESHOLD`` reads its reset value after it.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20: the TRNG is released, the
Key Manager and every crypto engine are held. The noise model drives
``balanced`` on all 12 lanes from before the first TRNG reset release; a burst
drives ``stuck0`` on all lanes for whole windows (W strobes of
``esrc_decor_valid_o``), then the four break words (``BREAK``), then
``balanced`` again. Every ESRC start is a clean start of the window W.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the drawn threshold T_d (4, 5 or 7), the order of the thresholds 0, 3
and T_d, the window of each threshold (256 or 512), the clean gap of the
consecutive leg (2, 3 or 4 windows), the order of the two trips of each
threshold, and the masks and the permutation of ``balanced``.

Checkers:
  CHK-PF-RESET    ALERT_THRESHOLD reads 0x4 after a TRNG reset that follows a
                  write of 7. Control: it read 7 before the reset.
  CHK-PF-TRIP-COUNT  every trip: exactly T failing windows (an exact burst,
                  below), then clean noise. ALERT reads 1 within LAT_WINDOWS
                  windows of words from the start of window T (a wait bound,
                  not a graded latency), PF reads 1, and the peak of
                  ANY_FAIL_COUNT is at least T. Control: ALERT = PF = 0 and
                  ANY_FAIL_COUNT = 0 before the burst.
  CHK-PF-TRIP-HOLD   every trip: at a read after the clean window that follows
                  window T has ended, ALERT = PF = 1, and ANY_FAIL_COUNT never
                  read above T. Control: the clean noise ran for at least
                  W + W/8 words after the break words.
  OBS-PF-TRIP-LATENCY  every trip: T, ANY_FAIL_COUNT at the first poll with
                  ALERT = 1, and the word and window of that poll relative to
                  the end of window T. Logged, not graded: no text states the
                  trip latency.
  CHK-PF-NOTRIP   an exact burst of T - 1 failing windows, then clean noise:
                  ALERT = PF = 0 at every poll up to LAT_WINDOWS windows of
                  words from the start of window T - 1 (the alert bound of the
                  trip legs), the peak of ANY_FAIL_COUNT is T - 1, and
                  ANY_FAIL_COUNT reads 0 at the last read. Control: the trips
                  of the same threshold reach the alert and the peak is
                  non-zero.
  CHK-PF-CONSEC   two bursts of T - 2 stuck windows with a clean gap: the peak
                  of ANY_FAIL_COUNT of each burst is at least T - 2, no alert
                  at any poll up to LAT_WINDOWS windows of words after the
                  second burst, and the count clears by the wrap 2W words after
                  the break words (below). A burst of n x W stuck words holds a
                  zero run above REPETITION_LIMIT = 200 for its last
                  n x W - 200 > (n - 1) x W words, so at least n windows fail
                  in it, whatever its offset to the window wraps. Control: T + 1 trips.
  CHK-PF-DISABLE  T = 0, ten stuck windows: no alert at any poll up to
                  LAT_WINDOWS windows of words after the burst, ANY_FAIL_COUNT
                  peak > 8, and after the burst the count clears by the wrap 2W
                  words after the break words (below).
                  Control: T = 3 trips with the same pattern.
  CHK-PF-HALT     after a trip, BUSY = 0 and a drain: LEVEL stays 0 and
                  ``esrc_compress_vld_o`` is silent for H = t_ref. Control: the
                  clean run shows 24 stream strobes in t_ref.
  CHK-PF-RECOVER  W1C: both bits 0 and the output stays halted for H; a
                  MODULE_ENABLE cycle or a TRNG reset restarts the output
                  (BOOT_PHASE_DONE = 1, LEVEL rises); the reset clears both bits.
                  After the TRNG reset the leaf writes no CTRL before the grade:
                  MODULE_ENABLE keeps its reset value 1, the leaf writes the
                  clean limits of the reset window W0 = 2048 and BYPASS only
                  (``SepEsrcCleanStart.run_live``), and BOOT_PHASE_DONE and
                  LEVEL then show that the reset alone ended AlertHang.
                  Control: both bits read 1 before the clear and the reset.
Count clear of CHK-PF-CONSEC and CHK-PF-DISABLE: ANY_FAIL_COUNT clears after an
accepted passing window (``entropy_source.adoc:71``). The window that holds the
break words ends at most W words after them and the next window holds clean
noise only, so the count is 0 from the wrap 2W words after the break words. A
read of the count must read 0, and every read issued more than 2W words after
the break words must read 0 (``zero_word``, ``last_nonzero_word``). The word
count is taken at the issue of the read, so the read latency is not in the
bound. A DUT that keeps the count one more clean window fails.
Exact burst of n failing windows: ANY_FAIL_COUNT reads 0, then stuck0 from
the next strobe and back-to-back reads of ANY_FAIL_COUNT. ANY_FAIL_COUNT counts
one failing window at each window wrap (``architecture.adoc:136``), so the
first read of n - 1 comes just after the wrap that starts window n (word o).
A window that holds no stuck word passes (the clean-window rule below), so the
first failing window ends at word 1 or later and the wrap that ends failing
window n - 1 comes after word (n - 2) x W: CHK-PF-TRIP-COUNT, CHK-PF-TRIP-HOLD
and CHK-PF-NOTRIP fail with ``reason=early:count_<n - 1>`` when o <= (n - 2) x W
(``wrap_obs`` = [word of the read before, o], ``expect_wrap_word_gt``).
Stuck0 stays until word o + W - W/8, then the break words and balanced. Window
n holds at least 7W/8 >= 224 stuck words, a zero run above REPETITION_LIMIT =
200 inside the window alone, so it fails. The break words end every
stream-bit zero run W/8 - 4 >= 28 words before the next wrap, so the next
window holds clean noise only and no health test fails in it. The leaf logs
the sum of the ``*_TOTAL_FAILS`` counters after the wrap that ends window n
minus the sum at that wrap (``test_fails_after_window_n``), the DUT record
that the later windows hold no failure. Before the consecutive leg and before
the first trip of a block, a leg that left ALERT, PF or ANY_FAIL_COUNT set is
followed by a restart (``OBS-PF-LEG-RESTART``). CHK-PF-TRIP-HOLD and
CHK-PF-NOTRIP grade the peak of ANY_FAIL_COUNT as exactly n, so a misplaced
switch fails a check and never passes one. Vector bit 15 of
``sep_internal_interrupts_probe_o`` is logged as ``OBS-PIC16``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_esrc_pattern_noise import (
    NUM_LANES,
    Balanced,
    EsrcStrobeTimeout,
    SepEsrcPatternNoise,
    Stuck,
    balanced_lanes,
    describe,
)
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_esrc_af_clear_bound,
)
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, poll_until
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, sym
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    ESRC_ALERT_SUMMARY_FAIL_COUNTS,
    ESRC_ALERT_THRESHOLD,
    ESRC_CTRL,
    ESRC_FIFO_RDATA,
    ESRC_FIFO_STATUS,
    ESRC_INTR_ENABLE,
    ESRC_INTR_STATUS,
    ESRC_MAIN_SM_STATUS,
)
from seq_lib.sep_esrc_clean_start_seq import (
    LATENCY_FACTOR,
    RESET_WINDOW,
    SepEsrcCleanStart,
    SepEsrcLeafSetup,
)

TEST = "sep_esrc_persistent_alert_rand_test"

ESRC_SHA256_STATUS = sym("ENTROPY_SOURCE_SHA256_STATUS_REG_ADDR")
TOTAL_ADDRS = tuple(
    sym(f"ENTROPY_SOURCE_{name}_TOTAL_FAILS_REG_ADDR")
    for name in ("REPCNT", "APT_HI", "APT_LO", "MARKOV_HI", "MARKOV_LO")
)

BASELINE_PARK = ("otbn", "aes", "hmac", "kmac", "abr")
T_DRAWN = (4, 5, 7)
WINDOWS = (256, 512)
GAPS = (2, 3, 4)
DISABLE_WINDOWS = 10
STREAM_STROBES = 24  # three digests of 8 words (architecture.adoc:142)


def _fm(reg: str, field: str) -> tuple[int, int]:
    meta = ENTROPY_SOURCE.fields(reg)[field]
    return meta["bm"], meta["bp"]


M_ALERT, _ = _fm("MAIN_SM_STATUS", "ALERT")
M_BOOT, _ = _fm("MAIN_SM_STATUS", "BOOT_PHASE_DONE")
M_PF, _ = _fm("INTR_STATUS", "PERSISTENT_FAILURE")
M_LEVEL, _ = _fm("FIFO_STATUS", "LEVEL")
M_BUSY, _ = _fm("SHA256_STATUS", "BUSY")
M_ANY, _ = _fm("ALERT_SUMMARY_FAIL_COUNTS", "ANY_FAIL_COUNT")
M_THR, _ = _fm("ALERT_THRESHOLD", "THRESHOLD")
THR_FIELDS = ENTROPY_SOURCE.mask("ALERT_THRESHOLD")
THR_RESET = ENTROPY_SOURCE.reset("ALERT_THRESHOLD")  # 0x4 (entropy_source.adoc:762)
INTR_ENABLE_ALL = ENTROPY_SOURCE.mask("INTR_ENABLE")
CTRL_OFF = ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=0)
CTRL_ON = ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=1)

STREAM_CAP_STROBES = 256  # outer limit of the first 24-word stream count, in strobes
DRAIN_ROUNDS = 64

# The stuck words of the last failing window of an exact burst stop W/TAIL_DIV
# words before the end of that window (see the module docstring).
TAIL_DIV = 8
# A trip waits for ALERT up to this many windows of words from the start of
# window T: window T, the window in which the design acts, and two windows of
# slack. A wait bound only; the trip latency is logged, not graded.
LAT_WINDOWS = 4
# ANY_FAIL_COUNT clears at the latest at the wrap CLEAR_WINDOWS windows of words
# after the last failing word: the rest of the window that holds it, then one
# clean window (entropy_source.adoc:71: it clears after an accepted passing window).
CLEAR_WINDOWS = 2

STUCK0 = [Stuck(0)] * NUM_LANES
STUCK1 = [Stuck(1)] * NUM_LANES
# The break words that end a stuck0 burst. The BIW stage computes y = a*b + c in
# GF(2^8) over three sets of four lanes (architecture.adoc:115). All lanes at 1
# give 0xFF*0xFF + 0xFF, which leaves some stream bits at 0, so one break word
# does not end every stream-bit run. Then one word per set with that set at 1
# and the other two at 0: in the word of the addend set every stream byte reads
# 0xFF, whichever set is the addend, so every stream-bit zero run ends inside the
# break.
SETS = 3
BREAK = [STUCK1] + [
    [Stuck(1) if lane // (NUM_LANES // SETS) == k else Stuck(0) for lane in range(NUM_LANES)]
    for k in range(SETS)
]


@dataclass(frozen=True)
class Plan:
    seed: int
    t_d: int
    order: tuple[int, ...]
    window: dict[int, int]
    gap: dict[int, int]
    trips: dict[int, tuple[str, str]]
    balanced: tuple[Balanced, ...]

    def describe(self) -> str:
        blocks = " ".join(
            f"T{t}:win={self.window[t]}"
            + (f",gap={self.gap[t]},trips={'+'.join(self.trips[t])}" if t else "")
            for t in self.order
        )
        return (
            f"t_d={self.t_d} order={','.join(str(t) for t in self.order)} {blocks} "
            f"{describe(self.balanced)}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    t_d = rng.choice(T_DRAWN)
    order = [0, 3, t_d]
    rng.shuffle(order)
    window: dict[int, int] = {}
    gap: dict[int, int] = {}
    trips: dict[int, tuple[str, str]] = {}
    for t in (0, 3, t_d):
        window[t] = rng.choice(WINDOWS)
        if t:
            gap[t] = rng.choice(GAPS)
            tr = ["E", "R"]
            rng.shuffle(tr)
            trips[t] = (tr[0], tr[1])
    balanced = tuple(balanced_lanes(rng))
    return Plan(seed, t_d, tuple(order), window, gap, trips, balanced)


class _Esrc(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


@dataclass
class _Block:
    """Results of one threshold block, graded after its last leg."""

    thr: int
    win: int
    t_ref: int | None = None
    notrip: dict | None = None
    consec: dict | None = None
    trip_alert: list[int] | None = None
    start_timeout: str | None = None


@pyuvm.test()
class sep_esrc_persistent_alert_rand_test(sep_base_test):
    """Threshold reset value, trip, no trip, consecutive gap, disable, halt and exits."""

    required_evidence = (
        "CHK-PF-RESET",
        "CHK-PF-TRIP-COUNT",
        "CHK-PF-TRIP-HOLD",
        "CHK-PF-NOTRIP",
        "CHK-PF-CONSEC",
        "CHK-PF-DISABLE",
        "CHK-PF-HALT",
        "CHK-PF-RECOVER",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=BASELINE_PARK)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        self.esrc = _Esrc(self)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        self.noise.start(list(plan.balanced))
        self.vld: SepBitWatch | None = None
        self.p: int | None = None
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)
        self.stream_clean: int | None = None
        self.trip_results: dict[int, dict] = {}
        self.disable_result: dict | None = None
        self.started = False
        self.trip_graded = False

        await self._reset_value_leg()
        for thr in plan.order:
            if thr == 0:
                await self._block_disable()
            else:
                await self._block_trip(thr)
        close_graded_window(self.logger)
        self._grade_disable()

        await self.noise.stop()
        if self.vld is not None:
            await self.vld.stop()
        await self.clk.stop()
        self.chk.finish()

    # --- bus, clocks and bounds ----------------------------------------------------
    def _now(self) -> int:
        return self.clk.clk

    async def _rd(self, addr: int) -> int:
        return await self.esrc._rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.esrc._wr(addr, data)

    def _clocks(self, words: int) -> int:
        assert self.p is not None, "strobe period not measured"
        return words * self.p

    def _word_bound(self, count: int, win: int) -> int:
        """Clocks for ``count`` strobes: the count plus at most one window."""
        return self._clocks(count + min(count, win) + 1)

    def _boot_bound(self, win: int) -> int:
        return self._clocks(2 * win + 64)

    def _latency_bound(self) -> int:
        assert self.stream_clean is not None
        return LATENCY_FACTOR * self.stream_clean

    def _pic16(self) -> int:
        v = self.rd(cocotb.top.sep_internal_interrupts_probe_o, allow_unknown=True)
        return (v >> 15) & 1

    # --- reset and start -----------------------------------------------------------
    async def _trng_reset(self) -> int:
        """TRNG bit 0 then 1 (SepEsrcLeafSetup). Returns the strobe mark at the release."""
        mark = await self.setup.trng_reset()
        if self.vld is None:
            self.vld = SepBitWatch(
                cocotb.top.esrc_compress_vld_o, name="esrc_compress_vld_o"
            ).start()
        return mark

    async def _clean_start(self, win: int, thr: int | None, release_mark: int | None) -> None:
        extra = [(ESRC_INTR_ENABLE, INTR_ENABLE_ALL)]
        if thr is not None:
            extra.append(
                (ESRC_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=thr))
            )
        cs = SepEsrcCleanStart(
            self, self.noise, list(self.plan.balanced), window=win, extra_writes=extra
        )
        if release_mark is None:
            await cs.run()
        else:
            await cs.run(release_mark=release_mark)
        self.p = await self.setup.measure_period(self.chk)

    async def _boot_and_level(self, win: int, what: str) -> tuple[bool, bool]:
        """Poll BOOT_PHASE_DONE to 1, then LEVEL above 0. Returns (boot_done, level_rose)."""
        boot, _ = await poll_until(
            lambda: self._rd(ESRC_MAIN_SM_STATUS),
            self._now,
            M_BOOT,
            M_BOOT,
            self._boot_bound(win),
        )
        if not boot:
            self.logger.info("%s: BOOT_PHASE_DONE not 1 bound=%d", what, self._boot_bound(win))
            return False, False
        bound = self._latency_bound() if self.stream_clean else self._clocks(STREAM_CAP_STROBES)
        level, _ = await self._poll_level_gt0(bound)
        if not level:
            self.logger.info("%s: FIFO_STATUS.LEVEL stayed 0 bound=%d", what, bound)
        return True, level

    async def _poll_level_gt0(self, bound: int) -> tuple[bool, list]:
        t0 = self._now()
        samples = []
        while self._now() - t0 <= bound:
            v = await self._rd(ESRC_FIFO_STATUS)
            samples.append(v)
            if v & M_LEVEL:
                return True, samples
        return False, samples

    async def _start_seq(self, thr: int, win: int) -> None:
        """Reset sequence, clean start with T and W, BOOT_PHASE_DONE and LEVEL.

        The first start of the leaf is bring-up: a failure raises ``AssertionError``.
        A later failure raises ``TrialTimeout``; the leg that owns the start fails its
        check with ``reason=timeout:start`` and the leaf goes on.
        """
        close_graded_window(self.logger)
        mark = await self._trng_reset()
        await self._clean_start(win, thr, mark)
        boot, level = await self._boot_and_level(win, "start")
        if not (boot and level):
            what = f"start_boot{int(boot)}_level{int(level)}"
            if self.started:
                raise TrialTimeout(what, self._boot_bound(win))
            raise AssertionError(
                f"ESRC start thr={thr} win={win} boot_done={int(boot)} level_rose={int(level)}"
            )
        self.started = True

    # --- FIFO and stream -------------------------------------------------------------
    async def _drain(self) -> bool:
        """Pop FIFO_RDATA until LEVEL reads 0 (bounded rounds)."""
        for _ in range(DRAIN_ROUNDS):
            lvl = (await self._rd(ESRC_FIFO_STATUS)) & M_LEVEL
            if lvl == 0:
                return True
            for _ in range(lvl):
                await self._rd(ESRC_FIFO_RDATA)
        return False

    async def _count_stream(self, n: int, bound: int, box: list[int]) -> None:
        """Count high clocks of esrc_compress_vld_o up to ``n``; box gets the clocks taken."""
        dut = cocotb.top
        seen = 0
        for clk in range(1, bound + 1):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.esrc_compress_vld_o):
                seen += 1
                if seen >= n:
                    box.append(clk)
                    return

    async def _measure_t_ref(self) -> int | None:
        """Clocks from the end of a drain to the 24th stream strobe, popping meanwhile."""
        await self._drain()
        bound = (
            self._clocks(STREAM_CAP_STROBES)
            if self.stream_clean is None
            else LATENCY_FACTOR * self.stream_clean
        )
        box: list[int] = []
        task = cocotb.start_soon(self._count_stream(STREAM_STROBES, bound, box))
        while not task.done():
            lvl = (await self._rd(ESRC_FIFO_STATUS)) & M_LEVEL
            for _ in range(lvl):
                await self._rd(ESRC_FIFO_RDATA)
        await task
        if not box:
            self.chk.ctrl(
                "PF-STREAM", False, strobes_lt=STREAM_STROBES, reason="timeout:stream", bound=bound
            )
            return None
        t_ref = box[0]
        if self.stream_clean is None:
            self.stream_clean = t_ref
        self.logger.info("t_ref=%d clk_i (24 stream strobes) bound=%d", t_ref, bound)
        return t_ref

    async def _hold(self, hold: int) -> tuple[int, int]:
        """Poll LEVEL back to back for ``hold`` clocks. Returns (level_max, stream high clocks)."""
        assert self.vld is not None
        m = self.vld.mark()
        t0 = self._now()
        level_max = 0
        while self._now() - t0 < hold:
            level_max = max(level_max, (await self._rd(ESRC_FIFO_STATUS)) & M_LEVEL)
        return level_max, self.vld.high_clocks_since(m)

    # --- noise schedule ----------------------------------------------------------------
    async def _schedule(
        self, segs: list[tuple[list, int]], win: int, done: list[int] | None = None
    ) -> None:
        """Drive each segment for its words; then ``balanced`` from the next strobe.

        ``done[0]`` counts the segments that have ended.
        """
        for pats, words in segs:
            self.noise.set_lanes(pats)
            await self.noise.wait_words(words, self._word_bound(words, win))
            if done is not None:
                done[0] += 1
        self.noise.set_lanes(list(self.plan.balanced))

    def _burst_segs(self, windows: int, win: int, tail_words: int = 0) -> list[tuple[list, int]]:
        segs = [(STUCK0, windows * win)] + [(word, 1) for word in BREAK]
        if tail_words:
            segs.append((list(self.plan.balanced), tail_words))
        return segs

    async def _to_clean(self) -> None:
        """The break words, then balanced. With no strobe a break word is skipped."""
        bound = self._clocks(2)
        for word in BREAK:
            self.noise.set_lanes(word)
            m = self.noise.mark()
            t0 = self._now()
            while self.noise.words_since(m) < 1 and self._now() - t0 <= bound:
                await RisingEdge(cocotb.top.clk_i)
            if self.noise.words_since(m) < 1:
                self.chk.obs("PF-BREAK", strobes=0, bound=bound)
        self.noise.set_lanes(list(self.plan.balanced))

    async def _fail_totals(self) -> int:
        """Sum of the five per-test failure counters (``*_TOTAL_FAILS``)."""
        total = 0
        for addr in TOTAL_ADDRS:
            total += await self._rd(addr)
        return total

    async def _ensure_clean(self, thr: int, win: int, leg: str) -> None:
        """Restart the ESRC if the previous leg left ALERT, PF or ANY_FAIL_COUNT set.

        A failing leg then cannot change the start state of the next leg. Raises
        ``TrialTimeout`` from the start sequence.
        """
        a, f, cnt = await self._poll_triple()
        if a or f or cnt:
            self.chk.obs("PF-LEG-RESTART", thr=thr, leg=leg, alert=int(a), pf=int(f), any_fail=cnt)
            close_graded_window(self.logger)
            await self._start_seq(thr, win)
            await self._drain()
            open_graded_window(TEST, self.logger)

    async def _poll_triple(self) -> tuple[int, int, int]:
        sm = await self._rd(ESRC_MAIN_SM_STATUS)
        st = await self._rd(ESRC_INTR_STATUS)
        cnt = await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)
        return (sm & M_ALERT) != 0, (st & M_PF) != 0, cnt & M_ANY

    async def _burst_and_settle(self, segs, win: int, split: int | None = None) -> dict:
        """Run ``segs`` while polling, then poll for LAT_WINDOWS windows of words.

        The last segment ends with the break words, the last failing words. The
        window that holds them ends at most W words later, and the next window
        holds clean noise only, so ANY_FAIL_COUNT clears at the latest at the wrap
        2W words after the last segment (``ALERT_SUMMARY_FAIL_COUNTS``: it clears
        after an accepted passing window). ``zero``: a read of ANY_FAIL_COUNT reads
        0, and no read issued more than CLEAR_WINDOWS x W words after the last
        segment reads a non-zero count. The word count is taken at the issue of the
        read, so the read latency is outside the bound. ALERT and PF are polled to
        LAT_WINDOWS windows of words after the last segment, the alert bound of the
        trip legs. With ``split`` the peak of ANY_FAIL_COUNT is kept apart for the
        polls before segment ``split`` has ended (burst 1) and for the polls after
        (burst 2). The FCOV sampler gets the same bound (``set_esrc_af_clear_bound``).
        """
        self.noise.byte_check(True)
        c0, mm0 = self.noise.byte_control()
        done = [0]
        task = cocotb.start_soon(self._schedule(segs, win, done))
        alert = pf = 0
        peak = 0
        peaks = [0, 0]
        polls = 0

        def track(a: bool, f: bool, cnt: int) -> None:
            nonlocal alert, pf, peak, polls
            alert |= a
            pf |= f
            peak = max(peak, cnt)
            k = 1 if split is not None and done[0] >= split else 0
            peaks[k] = max(peaks[k], cnt)
            polls += 1

        while not task.done():
            track(*(await self._poll_triple()))
        timeout = None
        try:
            await task
        except EsrcStrobeTimeout as exc:
            timeout = f"timeout:strobes bound={exc.bound}"
        bound = CLEAR_WINDOWS * win
        look = LAT_WINDOWS * win
        look_bound = self._word_bound(look, win)
        m = self.noise.mark()
        set_esrc_af_clear_bound(bound, self.logger)
        t0 = self._now()
        after = None
        zero_word = None
        nonzero_word = None
        while timeout is None and self._now() - t0 <= look_bound:
            sm = await self._rd(ESRC_MAIN_SM_STATUS)
            st = await self._rd(ESRC_INTR_STATUS)
            issued = self.noise.words_since(m)
            cnt = (await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)) & M_ANY
            track((sm & M_ALERT) != 0, (st & M_PF) != 0, cnt)
            if cnt == 0 and zero_word is None:
                zero_word = issued
            if cnt != 0:
                nonzero_word = issued
            if after is None and issued > bound:
                after = cnt
            if self.noise.words_since(m) >= look:
                break
        set_esrc_af_clear_bound(0, self.logger)
        watch = self.noise.words_since(m)
        if timeout is None and watch < look:
            timeout = f"timeout:strobes bound={look_bound}"
        c1, mm1 = self.noise.byte_control()
        self.noise.byte_check(False)
        self.chk.ctrl("NOISE-BYTES", mm1 == mm0 and c1 > c0, compared=c1 - c0, mismatched=mm1 - mm0)
        return {
            "alert": int(alert),
            "pf": int(pf),
            "peak": peak,
            "peaks": peaks if split is not None else None,
            "watch_words": watch,
            "after": after,
            "zero": (
                timeout is None
                and after == 0
                and zero_word is not None
                and (nonzero_word is None or nonzero_word <= bound)
            ),
            "zero_word": zero_word,
            "nonzero_word": nonzero_word,
            "polls": polls,
            "bound": bound,
            "timeout": timeout,
        }

    async def _exact_burst(self, win: int, target: int, trip: bool) -> dict:
        """Exactly ``target`` failing windows, then clean noise (module docstring).

        Polls ALERT, PF and ANY_FAIL_COUNT at least until word o + 2W + W/8, the end
        of the clean window after window ``target`` plus the margin. With ``trip``
        the polls go on until ALERT reads 1, at most o + LAT_WINDOWS x W words.
        Without ``trip`` the polls go on to word o + LAT_WINDOWS x W, the alert
        bound of the trip legs, so a late alert inside that bound fails the leg.
        """
        res: dict = {"reason": None, "peak": 0, "alert_any": 0, "pf_any": 0}
        self.noise.byte_check(True)
        c0, mm0 = self.noise.byte_control()
        a0, f0, cnt0 = await self._poll_triple()
        res.update(alert_before=int(a0), pf_before=int(f0), count_before=cnt0)
        self.noise.set_lanes(STUCK0)
        m = self.noise.mark()

        def poll_word() -> int:
            return self.noise.words_since(m)

        def track(a: bool, f: bool, cnt: int) -> None:
            res["alert_any"] |= int(a)
            res["pf_any"] |= int(f)
            res["peak"] = max(res["peak"], cnt)

        track(a0, f0, cnt0)
        o_prev = 0
        o = None
        if cnt0 != 0:
            res["reason"] = "count_not_zero_before"
        else:
            bound = self._word_bound(target * win, win)
            t0 = self._now()
            while self._now() - t0 <= bound:
                cnt = (await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)) & M_ANY
                w = poll_word()
                track(False, False, cnt)
                if cnt >= target - 1:
                    o = w
                    break
                o_prev = w
            if o is None:
                res["reason"] = f"timeout:count_{target - 1}"
                res["bound"] = bound
        if o is not None:
            # n - 1 failing windows need more than (n - 2) x W stuck words (module
            # docstring), so a read of n - 1 at or before that word is an early count.
            early_max = (target - 2) * win
            res.update(wrap_obs=[o_prev, o], expect_wrap_word_gt=early_max)
            if o <= early_max:
                res["reason"] = f"early:count_{target - 1}"
            stop = o + win - win // TAIL_DIV
            bound = self._word_bound(win, win)
            t0 = self._now()
            while poll_word() < stop and self._now() - t0 <= bound:
                track(*(await self._poll_triple()))
            if poll_word() < stop and res["reason"] is None:
                res["reason"] = f"timeout:strobes bound={bound}"
        await self._to_clean()
        switch = poll_word()
        if o is not None and res["reason"] is None:
            end = o + 2 * win + win // TAIL_DIV
            last = o + LAT_WINDOWS * win
            need = end if trip else last
            bound = self._word_bound(LAT_WINDOWS * win, win)
            t0 = self._now()
            while self._now() - t0 <= bound:
                a, f, cnt = await self._poll_triple()
                w = poll_word()
                track(a, f, cnt)
                if cnt >= target and "totals_at_n" not in res:
                    res["totals_at_n"] = await self._fail_totals()
                    res["count_at_n"] = cnt
                if a and "alert_word" not in res:
                    res.update(alert_word=w, alert_count=cnt)
                if trip and w >= end and res["alert_any"]:
                    break
                if w >= last:
                    break
            res["watch_words"] = poll_word() - o
            if poll_word() < need:
                res["reason"] = f"timeout:strobes bound={bound}"
            elif trip and not res["alert_any"]:
                res["reason"] = "timeout:alert"
                res["bound_words"] = last - o
        a, f, cnt = await self._poll_triple()
        track(a, f, cnt)
        if "totals_at_n" in res:
            # Health-test failures that the DUT recorded after the wrap that ends
            # window n: 0 when the windows after window n hold clean noise only.
            res["test_fails_after_window_n"] = await self._fail_totals() - res["totals_at_n"]
        res.update(
            o=o,
            alert_final=int(a),
            pf_final=int(f),
            count_final=cnt,
            final_word=poll_word(),
            clean_words=poll_word() - switch,
        )
        c1, mm1 = self.noise.byte_control()
        self.noise.byte_check(False)
        self.chk.ctrl("NOISE-BYTES", mm1 == mm0 and c1 > c0, compared=c1 - c0, mismatched=mm1 - mm0)
        return res

    async def _trip(self, thr: int, win: int) -> dict:
        """An exact burst of T failing windows; grades TRIP-COUNT and TRIP-HOLD."""
        self.trip_graded = True
        r = await self._exact_burst(win, thr, trip=True)
        reason = {"reason": r["reason"]} if r["reason"] else {}
        self.chk.ctrl(
            "PF-TRIP-COUNT",
            r["alert_before"] == 0 and r["pf_before"] == 0 and r["count_before"] == 0,
            thr=thr,
            alert_before=r["alert_before"],
            pf_before=r["pf_before"],
            count_before=r["count_before"],
        )
        self.chk.ok(
            "PF-TRIP-COUNT",
            r["reason"] is None and r["peak"] >= thr and r["alert_any"] and r["pf_final"],
            **reason,
            thr=thr,
            win=win,
            failing_windows=thr,
            any_fail_peak=r["peak"],
            expect_any_fail_peak_min=thr,
            alert=r["alert_any"],
            pf=r["pf_final"],
            wrap_obs=r.get("wrap_obs"),
            expect_wrap_word_gt=r.get("expect_wrap_word_gt"),
            alert_bound_windows=LAT_WINDOWS,
        )
        o = r["o"]
        rel_final = None if o is None else r["final_word"] - (o + win)
        hold_min = win + win // TAIL_DIV
        self.chk.ctrl(
            "PF-TRIP-HOLD",
            r["clean_words"] >= hold_min,
            thr=thr,
            clean_words=r["clean_words"],
            expect_clean_words_min=hold_min,
        )
        self.chk.ok(
            "PF-TRIP-HOLD",
            r["reason"] is None and r["alert_final"] and r["pf_final"] and r["peak"] == thr,
            **reason,
            thr=thr,
            win=win,
            read_word_after_window_t=rel_final,
            alert_after_clean=r["alert_final"],
            pf_after_clean=r["pf_final"],
            any_fail_peak=r["peak"],
            expect_any_fail_peak=thr,
            any_fail_final=r["count_final"],
            test_fails_after_window_t=r.get("test_fails_after_window_n"),
        )
        lat = {}
        if o is not None and "alert_word" in r:
            rel = r["alert_word"] - (o + win)
            lat = {
                "alert_word_after_window_t": rel,
                "alert_window": thr + (r["alert_word"] - o) // win,
                "any_fail_at_alert": r["alert_count"],
            }
        self.chk.obs(
            "PF-TRIP-LATENCY",
            thr=thr,
            win=win,
            wrap_obs=r.get("wrap_obs"),
            pic16=self._pic16(),
            **lat,
            **reason,
        )
        return {
            "alert": int(r["reason"] is None and bool(r["alert_any"])),
            "alert_after": r["alert_final"],
            "pf": r["pf_final"],
            "bound": r.get("bound", r.get("bound_words")),
            **reason,
        }

    # --- legs --------------------------------------------------------------------------
    async def _reset_value_leg(self) -> None:
        close_graded_window(self.logger)
        await self._trng_reset()
        await self._wr(ESRC_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=7))
        before = await self._rd(ESRC_ALERT_THRESHOLD)
        self.chk.ctrl("PF-RESET", before & THR_FIELDS == 7, before=f"0x{before & THR_FIELDS:x}")
        try:
            await self._trng_reset()
        except TrialTimeout as exc:
            self.chk.ok("PF-RESET", False, reason=f"timeout:{exc.what}", bound=exc.bound)
            return
        # The graded window opens after the reset: the stored 7 of the control write
        # is never sampled; the stored-value sample and this read see the reset value.
        open_graded_window(TEST, self.logger)
        after = await self._rd(ESRC_ALERT_THRESHOLD)
        close_graded_window(self.logger)
        self.chk.ok(
            "PF-RESET",
            after & THR_FIELDS == THR_RESET,
            alert_threshold=f"0x{after & THR_FIELDS:x}",
            expect=f"0x{THR_RESET:x}",
            rsvd=f"0x{after & ~THR_FIELDS & 0xFFFF_FFFF:x}",
            ctrl_before=f"0x{before & THR_FIELDS:x}",
        )

    async def _block_trip(self, thr: int) -> None:
        plan = self.plan
        win = plan.window[thr]
        blk = _Block(thr, win)
        try:
            await self._start_seq(thr, win)
        except TrialTimeout as exc:
            blk.start_timeout = f"timeout:{exc.what} bound={exc.bound}"
            self.trip_results.setdefault(
                thr, {"alert": 0, "bound": exc.bound, "reason": blk.start_timeout}
            )
            for name in ("PF-TRIP-COUNT", "PF-TRIP-HOLD"):
                self.chk.ok(name, False, thr=thr, reason=blk.start_timeout)
            self._grade_block(blk)
            return
        blk.t_ref = await self._measure_t_ref()
        hold = blk.t_ref

        open_graded_window(TEST, self.logger)
        blk.notrip = await self._exact_burst(win, thr - 1, trip=False)
        n = thr - 2
        g = plan.gap[thr]
        first_burst = self._burst_segs(n, win, tail_words=g * win - len(BREAK))
        segs = first_burst + self._burst_segs(n, win)
        try:
            await self._ensure_clean(thr, win, "consec")
            blk.consec = await self._burst_and_settle(segs, win, split=len(first_burst))
        except TrialTimeout as exc:
            blk.consec = {"timeout": f"timeout:{exc.what} bound={exc.bound}"}
        close_graded_window(self.logger)

        alerts: list[int] = []
        first = True
        for kind in plan.trips[thr]:
            try:
                if first:
                    await self._ensure_clean(thr, win, "trip")
                    close_graded_window(self.logger)
                else:
                    await self._start_seq(thr, win)
                    await self._drain()
            except TrialTimeout as exc:
                close_graded_window(self.logger)
                self.trip_graded = False
                res = self._trip_start_timeout(thr, kind, exc)
                alerts.append(res["alert"])
                self.trip_results.setdefault(thr, res)
                first = False
                continue
            self.trip_graded = False
            try:
                if kind == "E":
                    res = await self._trip_e(thr, win, hold)
                else:
                    res = await self._trip_r(thr, win)
            except TrialTimeout as exc:
                close_graded_window(self.logger)
                res = self._trip_start_timeout(thr, kind, exc)
            alerts.append(res["alert"])
            self.trip_results.setdefault(thr, res)
            first = False
        blk.trip_alert = alerts
        self._grade_block(blk)

    def _trip_start_timeout(self, thr: int, kind: str, exc: TrialTimeout) -> dict:
        """A trip whose set-up or wait timed out: its exit check fails with the reason."""
        reason = f"timeout:{exc.what}"
        if not self.trip_graded:
            for name in ("PF-TRIP-COUNT", "PF-TRIP-HOLD"):
                self.chk.ok(name, False, thr=thr, reason=reason, bound=exc.bound)
        if kind == "E":
            self.chk.ok("PF-HALT", False, thr=thr, reason=reason, bound=exc.bound)
        self.chk.ok(
            "PF-RECOVER",
            False,
            thr=thr,
            exit="enable_cycle" if kind == "E" else "trng_reset",
            reason=reason,
            bound=exc.bound,
        )
        return {"alert": 0, "bound": exc.bound, "reason": reason}

    async def _trip_e(self, thr: int, win: int, hold: int | None) -> dict:
        """Trip ended by a MODULE_ENABLE cycle; grades HALT and RECOVER (enable_cycle)."""
        open_graded_window(TEST, self.logger)
        res = await self._trip(thr, win)
        pic = self._pic16()
        self.chk.obs("PIC16", value=pic, thr=thr)
        if not res["alert"]:
            close_graded_window(self.logger)
            self.chk.ok("PF-HALT", False, thr=thr, reason="timeout:alert", bound=res["bound"])
            self.chk.ok(
                "PF-RECOVER",
                False,
                thr=thr,
                exit="enable_cycle",
                reason="timeout:alert",
                bound=res["bound"],
            )
            return res
        # Halt leg: BUSY to 0 (popping meanwhile), drain, hold H.
        busy_clear = False
        if hold is not None:
            bound = self._latency_bound()
            t0 = self._now()
            while self._now() - t0 <= bound:
                if (await self._rd(ESRC_SHA256_STATUS)) & M_BUSY == 0:
                    busy_clear = True
                    break
                lvl = (await self._rd(ESRC_FIFO_STATUS)) & M_LEVEL
                for _ in range(lvl):
                    await self._rd(ESRC_FIFO_RDATA)
        drained = await self._drain()
        if hold is None or not busy_clear or not drained:
            self.chk.ok(
                "PF-HALT",
                False,
                thr=thr,
                sha_busy_clear=int(busy_clear),
                drained=int(drained),
                reason="timeout:busy_or_drain" if hold is not None else "no_t_ref",
            )
            level_max, vld = None, None
        else:
            level_max, vld = await self._hold(hold)
            self.chk.ok(
                "PF-HALT",
                level_max == 0 and vld == 0,
                thr=thr,
                sha_busy_clear=1,
                level_max=level_max,
                stream_vld=vld,
                hold_clk=hold,
                ctrl_stream_vld=STREAM_STROBES,
            )
        # Clear leg: W1C of ALERT and PERSISTENT_FAILURE, hold H, enable cycle.
        sm_before = await self._rd(ESRC_MAIN_SM_STATUS)
        st_before = await self._rd(ESRC_INTR_STATUS)
        bits_before = (sm_before & M_ALERT != 0) and (st_before & M_PF != 0)
        self.chk.ctrl(
            "PF-RECOVER",
            bits_before,
            exit="enable_cycle",
            alert_before=int(sm_before & M_ALERT != 0),
            pf_before=int(st_before & M_PF != 0),
        )
        await self._wr(ESRC_MAIN_SM_STATUS, M_ALERT)
        await self._wr(ESRC_INTR_STATUS, M_PF)
        alert_c = (await self._rd(ESRC_MAIN_SM_STATUS)) & M_ALERT != 0
        pf_c = (await self._rd(ESRC_INTR_STATUS)) & M_PF != 0
        if hold is not None:
            lvl_w1c, vld_w1c = await self._hold(hold)
        else:
            lvl_w1c, vld_w1c = None, None
        await self._wr(ESRC_CTRL, CTRL_OFF)
        await self._wr(ESRC_CTRL, CTRL_ON)
        boot, level = await self._boot_and_level(win, "enable_cycle")
        close_graded_window(self.logger)
        halted = lvl_w1c == 0 and vld_w1c == 0
        self.chk.ok(
            "PF-RECOVER",
            (not alert_c) and (not pf_c) and halted and boot and level,
            thr=thr,
            exit="enable_cycle",
            after_w1c_alert=int(alert_c),
            after_w1c_pf=int(pf_c),
            after_w1c_level=lvl_w1c,
            after_w1c_stream_vld=vld_w1c,
            boot_done=int(boot),
            level_rises=int(level),
        )
        return res

    async def _trip_r(self, thr: int, win: int) -> dict:
        """Trip ended by a TRNG reset; grades RECOVER (trng_reset)."""
        open_graded_window(TEST, self.logger)
        res = await self._trip(thr, win)
        if not res["alert"]:
            close_graded_window(self.logger)
            self.chk.ok(
                "PF-RECOVER",
                False,
                thr=thr,
                exit="trng_reset",
                reason="timeout:alert",
                bound=res["bound"],
            )
            return res
        self.chk.ctrl(
            "PF-RECOVER",
            res["alert_after"] and res["pf"],
            exit="trng_reset",
            alert_before=res["alert_after"],
            pf_before=res["pf"],
        )
        # No CTRL write from here to the grade: MODULE_ENABLE keeps its reset value 1
        # (entropy_source.adoc:112), so only the reset can end AlertHang. The live
        # start writes the clean limits of the reset window and no CTRL.
        mark = await self._trng_reset()
        alert_r = (await self._rd(ESRC_MAIN_SM_STATUS)) & M_ALERT != 0
        pf_r = (await self._rd(ESRC_INTR_STATUS)) & M_PF != 0
        await SepEsrcCleanStart(
            self, self.noise, list(self.plan.balanced), window=RESET_WINDOW
        ).run_live(release_mark=mark)
        boot, level = await self._boot_and_level(RESET_WINDOW, "trng_reset")
        close_graded_window(self.logger)
        self.chk.ok(
            "PF-RECOVER",
            (not alert_r) and (not pf_r) and boot and level,
            thr=thr,
            exit="trng_reset",
            window=RESET_WINDOW,
            alert_after_reset=int(alert_r),
            pf_after_reset=int(pf_r),
            after_w1c_level="na",
            boot_done=int(boot),
            level_rises=int(level),
        )
        return res

    async def _block_disable(self) -> None:
        win = self.plan.window[0]
        try:
            await self._start_seq(0, win)
        except TrialTimeout as exc:
            self.disable_result = {"win": win, "reason": f"timeout:{exc.what} bound={exc.bound}"}
            return
        # The burst, then clean noise until ANY_FAIL_COUNT reads 0 (two windows), all in
        # the graded window, so the count falls to 0 with the module enabled.
        open_graded_window(TEST, self.logger)
        r = await self._burst_and_settle(self._burst_segs(DISABLE_WINDOWS, win), win)
        close_graded_window(self.logger)
        self.disable_result = {
            "alert": r["alert"],
            "pf": r["pf"],
            "peak": r["peak"],
            "polls": r["polls"],
            "win": win,
            "after": r["after"],
            "zero": r["zero"],
            "watch_words": r["watch_words"],
            **self._clear_fields(r, win),
        }
        if r["timeout"]:
            self.disable_result["reason"] = r["timeout"]

    # --- grading -----------------------------------------------------------------------
    @staticmethod
    def _clear_fields(r: dict, win: int | None) -> dict:
        """The count-clear evidence of ``_burst_and_settle``, and its reason if it failed."""
        fields = {
            "zero_word": r.get("zero_word"),
            "last_nonzero_word": r.get("nonzero_word"),
            "expect_last_nonzero_word_max": CLEAR_WINDOWS * win if win else None,
        }
        if r.get("timeout") or r.get("zero", True):
            return fields
        fields["reason"] = "timeout:count_zero" if r.get("zero_word") is None else "late:count_zero"
        return fields

    def _grade_block(self, blk: _Block) -> None:
        tripped = bool(blk.trip_alert) and all(blk.trip_alert)
        nt = blk.notrip or {}
        self.chk.ctrl(
            "PF-NOTRIP",
            tripped and nt.get("peak", 0) > 0,
            thr=blk.thr,
            ctrl_trip=int(tripped),
            any_fail_peak=nt.get("peak"),
        )
        fields = {
            "thr": blk.thr,
            "win": blk.win,
            "failing_windows": blk.thr - 1,
            "alert": nt.get("alert_any"),
            "pf": nt.get("pf_any"),
            "any_fail_peak": nt.get("peak"),
            "expect_any_fail_peak": blk.thr - 1,
            "any_fail_after": nt.get("count_final"),
            "test_fails_after_window_n": nt.get("test_fails_after_window_n"),
            "wrap_obs": nt.get("wrap_obs"),
            "expect_wrap_word_gt": nt.get("expect_wrap_word_gt"),
            "watch_words": nt.get("watch_words"),
            "expect_watch_words_min": LAT_WINDOWS * blk.win,
        }
        if blk.start_timeout:
            fields["reason"] = blk.start_timeout
        elif nt.get("reason"):
            fields["reason"] = nt["reason"]
            if nt.get("bound") is not None:
                fields["bound"] = nt["bound"]
        self.chk.ok(
            "PF-NOTRIP",
            not blk.start_timeout
            and nt.get("reason") is None
            and nt.get("peak") == blk.thr - 1
            and nt.get("alert_any") == 0
            and nt.get("pf_any") == 0
            and nt.get("count_final") == 0,
            **fields,
        )
        cs = blk.consec or {}
        self.chk.ctrl("PF-CONSEC", tripped, thr=blk.thr, ctrl_single_burst_alert=int(tripped))
        peaks = cs.get("peaks")
        fields = {
            "thr": blk.thr,
            "bursts": [blk.thr - 2, blk.thr - 2],
            "gap": self.plan.gap[blk.thr],
            "alert": cs.get("alert"),
            "pf": cs.get("pf"),
            "any_fail_peaks": peaks,
            "expect_any_fail_peak_min": blk.thr - 2,
            "any_fail_after": cs.get("after"),
            "watch_words": cs.get("watch_words"),
            "expect_watch_words_min": LAT_WINDOWS * blk.win,
            "ctrl_single_burst_alert": int(tripped),
        }
        clear = self._clear_fields(cs, blk.win)
        fields.update({k: v for k, v in clear.items() if k != "reason"})
        if blk.start_timeout:
            fields["reason"] = blk.start_timeout
        elif cs.get("timeout"):
            fields["reason"] = cs["timeout"]
        elif "reason" in clear:
            fields["reason"] = clear["reason"]
        counted = peaks is not None and all(pk >= blk.thr - 2 for pk in peaks)
        if not fields.get("reason") and not counted:
            fields["reason"] = "burst_not_counted"
        self.chk.ok(
            "PF-CONSEC",
            cs.get("alert") == 0 and cs.get("pf") == 0 and cs.get("zero") and counted,
            **fields,
        )

    def _grade_disable(self) -> None:
        ctrl = self.trip_results.get(3, {})
        ctrl_ok = bool(ctrl.get("alert"))
        d = self.disable_result or {}
        self.chk.ctrl("PF-DISABLE", ctrl_ok, ctrl_thr3_alert=int(ctrl_ok))
        extra = {"reason": d["reason"]} if d.get("reason") else {}
        self.chk.ok(
            "PF-DISABLE",
            not d.get("reason")
            and d.get("alert") == 0
            and d.get("pf") == 0
            and d.get("peak", 0) > DISABLE_WINDOWS - 2
            and d.get("zero") is True,
            **extra,
            thr=0,
            win=d.get("win"),
            failing_windows=DISABLE_WINDOWS,
            alert=d.get("alert"),
            pf=d.get("pf"),
            any_fail=d.get("peak"),
            any_fail_after=d.get("after"),
            zero_word=d.get("zero_word"),
            last_nonzero_word=d.get("last_nonzero_word"),
            expect_last_nonzero_word_max=d.get("expect_last_nonzero_word_max"),
            watch_words=d.get("watch_words"),
            expect_watch_words_min=LAT_WINDOWS * d["win"] if d.get("win") else None,
            ctrl_thr3_alert=int(ctrl_ok),
        )
