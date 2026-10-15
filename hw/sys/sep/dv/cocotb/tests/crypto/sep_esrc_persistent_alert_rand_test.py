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
``esrc_decor_valid_o``), then one break word (all lanes 1 for one strobe), then
``balanced`` again. Every ESRC start is a clean start of the window W.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the drawn threshold T_d (4, 5 or 7), the order of the thresholds 0, 3
and T_d, the window of each threshold (256 or 512), the clean gap of the
consecutive leg (2, 3 or 4 windows), the order of the two trips of each
threshold, and the masks and the permutation of ``balanced``.

Checkers:
  CHK-PF-RESET    ALERT_THRESHOLD reads 0x4 after a TRNG reset that follows a
                  write of 7. Control: it read 7 before the reset.
  CHK-PF-TRIP     T_d: after a burst of T + 1 windows, ALERT = PF = 1 and
                  ANY_FAIL_COUNT >= T at the first poll with ALERT = 1.
                  Control: the trip at T = 3.
  CHK-PF-NOTRIP   a burst of T - 2 windows: ALERT = PF = 0 at every poll;
                  ANY_FAIL_COUNT reads 0 within two clean windows. Control: the
                  T + 1 burst trips and the count peak is non-zero.
  CHK-PF-CONSEC   two bursts of T - 2 windows with a clean gap: no alert; the
                  count reads 0 within two clean windows. Control: T + 1 trips.
  CHK-PF-DISABLE  T = 0, ten stuck windows: no alert, ANY_FAIL_COUNT peak > 8.
                  Control: T = 3 trips with the same pattern.
  CHK-PF-HALT     after a trip, BUSY = 0 and a drain: LEVEL stays 0 and
                  ``esrc_compress_vld_o`` is silent for H = t_ref. Control: the
                  clean run shows 24 stream strobes in t_ref.
  CHK-PF-RECOVER  W1C: both bits 0 and the output stays halted for H; a
                  MODULE_ENABLE cycle or a TRNG reset restarts the output
                  (BOOT_PHASE_DONE = 1, LEVEL rises); the reset clears both bits.
                  Control: both bits read 1 before the clear and the reset.
The burst of exactly T windows is logged as ``OBS-PF`` only; vector bit 15 of
``sep_internal_interrupts_probe_o`` is logged as ``OBS-pic16``.
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
from env.sep_fcov_gate import close_graded_window, open_graded_window
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
    SepEsrcCleanStart,
    SepEsrcLeafSetup,
)

TEST = "sep_esrc_persistent_alert_rand_test"

ESRC_SHA256_STATUS = sym("ENTROPY_SOURCE_SHA256_STATUS_REG_ADDR")

BASELINE_PARK = ("otbn", "aes", "hmac", "kmac", "abr")
T_DRAWN = (4, 5, 7)
WINDOWS = (256, 512)
GAPS = (2, 3, 4)
DISABLE_WINDOWS = 10
STREAM_STROBES = 24  # three digests of 8 words (architecture.adoc:142)
ALERT_EXTRA_WINDOWS = 3  # alert wait after the T + 1 burst, in whole windows


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

STUCK0 = [Stuck(0)] * NUM_LANES
STUCK1 = [Stuck(1)] * NUM_LANES


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
        "CHK-PF-TRIP",
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

        await self._reset_value_leg()
        for thr in plan.order:
            if thr == 0:
                await self._block_disable()
            else:
                await self._block_trip(thr)
        close_graded_window(self.logger)
        self._grade_trip_and_disable()

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
    async def _schedule(self, segs: list[tuple[list, int]], win: int) -> None:
        for pats, words in segs:
            self.noise.set_lanes(pats)
            await self.noise.wait_words(words, self._word_bound(words, win))

    def _burst_segs(self, windows: int, win: int, tail_words: int = 0) -> list[tuple[list, int]]:
        segs = [(STUCK0, windows * win), (STUCK1, 1)]
        if tail_words:
            segs.append((list(self.plan.balanced), tail_words))
        return segs

    async def _to_clean(self) -> None:
        """One break word, then balanced. With no strobe the break word is skipped."""
        self.noise.set_lanes(STUCK1)
        m = self.noise.mark()
        t0 = self._now()
        bound = self._clocks(2)
        while self.noise.words_since(m) < 1 and self._now() - t0 <= bound:
            await RisingEdge(cocotb.top.clk_i)
        if self.noise.words_since(m) < 1:
            self.chk.obs("PF-BREAK", strobes=0, bound=bound)
        self.noise.set_lanes(list(self.plan.balanced))

    async def _poll_triple(self) -> tuple[int, int, int]:
        sm = await self._rd(ESRC_MAIN_SM_STATUS)
        st = await self._rd(ESRC_INTR_STATUS)
        cnt = await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)
        return (sm & M_ALERT) != 0, (st & M_PF) != 0, cnt & M_ANY

    async def _burst_and_settle(self, segs, win: int) -> dict:
        """Run ``segs`` while polling; then poll until ANY_FAIL_COUNT reads 0 (2 windows)."""
        self.noise.byte_check(True)
        c0, mm0 = self.noise.byte_control()
        task = cocotb.start_soon(self._schedule(segs, win))
        alert = pf = 0
        peak = 0
        polls = 0
        while not task.done():
            a, f, cnt = await self._poll_triple()
            alert |= a
            pf |= f
            peak = max(peak, cnt)
            polls += 1
        timeout = None
        try:
            await task
        except EsrcStrobeTimeout as exc:
            timeout = f"timeout:strobes bound={exc.bound}"
        bound = self._word_bound(2 * win, win)
        t0 = self._now()
        after = None
        while timeout is None and self._now() - t0 <= bound:
            a, f, cnt = await self._poll_triple()
            alert |= a
            pf |= f
            peak = max(peak, cnt)
            polls += 1
            if cnt == 0:
                after = 0
                break
            after = cnt
        c1, mm1 = self.noise.byte_control()
        self.noise.byte_check(False)
        self.chk.ctrl("NOISE-BYTES", mm1 == mm0 and c1 > c0, compared=c1 - c0, mismatched=mm1 - mm0)
        return {
            "alert": int(alert),
            "pf": int(pf),
            "peak": peak,
            "after": after,
            "zero": after == 0 and timeout is None,
            "polls": polls,
            "bound": bound,
            "timeout": timeout,
        }

    async def _trip(self, thr: int, win: int) -> dict:
        """Stuck0 for at least T + 1 windows and until ALERT reads 1; then clean noise."""
        self.noise.byte_check(True)
        c0, mm0 = self.noise.byte_control()
        self.noise.set_lanes(STUCK0)
        m = self.noise.mark()
        min_words = (thr + 1) * win
        bound = self._word_bound(min_words + ALERT_EXTRA_WINDOWS * win, win)
        t0 = self._now()
        any_fail = None
        alert_word = None
        while self._now() - t0 <= bound:
            sm = await self._rd(ESRC_MAIN_SM_STATUS)
            if sm & M_ALERT:
                any_fail = (await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)) & M_ANY
                alert_word = self.noise.words_since(m)
                break
        while alert_word is not None and self.noise.words_since(m) < min_words:
            if self._now() - t0 > bound:
                break
            await RisingEdge(cocotb.top.clk_i)
        words = self.noise.words_since(m)
        c1, mm1 = self.noise.byte_control()
        self.noise.byte_check(False)
        self.chk.ctrl("NOISE-BYTES", mm1 == mm0 and c1 > c0, compared=c1 - c0, mismatched=mm1 - mm0)
        await self._to_clean()
        alert_rd = (await self._rd(ESRC_MAIN_SM_STATUS)) & M_ALERT != 0
        pf_rd = (await self._rd(ESRC_INTR_STATUS)) & M_PF != 0
        res = {
            "alert": int(alert_word is not None),
            "alert_after": int(alert_rd),
            "pf": int(pf_rd),
            "any_fail": any_fail,
            "failing_windows": words // win,
            "alert_at_word": alert_word,
            "bound": bound,
        }
        self.chk.obs(
            "PF-TRIP-RUN",
            thr=thr,
            win=win,
            pic16=self._pic16(),
            **{k: v for k, v in res.items() if v is not None},
        )
        return res

    # --- legs --------------------------------------------------------------------------
    async def _reset_value_leg(self) -> None:
        close_graded_window(self.logger)
        await self._trng_reset()
        await self._wr(ESRC_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=7))
        before = await self._rd(ESRC_ALERT_THRESHOLD)
        self.chk.ctrl("PF-RESET", before & THR_FIELDS == 7, before=f"0x{before & THR_FIELDS:x}")
        open_graded_window(TEST, self.logger)
        try:
            await self._trng_reset()
        except TrialTimeout as exc:
            close_graded_window(self.logger)
            self.chk.ok("PF-RESET", False, reason=f"timeout:{exc.what}", bound=exc.bound)
            return
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
            self._grade_block(blk)
            return
        blk.t_ref = await self._measure_t_ref()
        hold = blk.t_ref

        open_graded_window(TEST, self.logger)
        n = thr - 2
        blk.notrip = await self._burst_and_settle(self._burst_segs(n, win), win)
        g = plan.gap[thr]
        segs = self._burst_segs(n, win, tail_words=g * win - 1) + self._burst_segs(n, win)
        blk.consec = await self._burst_and_settle(segs, win)
        close_graded_window(self.logger)

        alerts: list[int] = []
        first = True
        for kind in plan.trips[thr]:
            if not first:
                try:
                    await self._start_seq(thr, win)
                except TrialTimeout as exc:
                    res = self._trip_start_timeout(thr, kind, exc)
                    alerts.append(res["alert"])
                    self.trip_results.setdefault(thr, res)
                    continue
                await self._drain()
            try:
                if kind == "E":
                    res = await self._trip_e(thr, win, hold)
                else:
                    res = await self._trip_r(thr, win)
            except TrialTimeout as exc:
                close_graded_window(self.logger)
                res = self._trip_start_timeout(thr, kind, exc)
            alerts.append(res["alert"])
            # The first trip of the block is the one CHK-PF-TRIP grades.
            self.trip_results.setdefault(thr, res)
            first = False
        blk.trip_alert = alerts
        await self._equal_case(thr, win)
        self._grade_block(blk)

    def _trip_start_timeout(self, thr: int, kind: str, exc: TrialTimeout) -> dict:
        """A trip whose set-up or wait timed out: its exit check fails with the reason."""
        reason = f"timeout:{exc.what}"
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
        self.chk.obs("pic16", value=pic, thr=thr)
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
        mark = await self._trng_reset()
        alert_r = (await self._rd(ESRC_MAIN_SM_STATUS)) & M_ALERT != 0
        pf_r = (await self._rd(ESRC_INTR_STATUS)) & M_PF != 0
        close_graded_window(self.logger)
        await self._clean_start(win, None, mark)
        boot, level = await self._boot_and_level(win, "trng_reset")
        self.chk.ok(
            "PF-RECOVER",
            (not alert_r) and (not pf_r) and boot and level,
            thr=thr,
            exit="trng_reset",
            alert_after_reset=int(alert_r),
            pf_after_reset=int(pf_r),
            after_w1c_level="na",
            boot_done=int(boot),
            level_rises=int(level),
        )
        return res

    async def _equal_case(self, thr: int, win: int) -> None:
        """A burst of exactly T windows: logged only (OBS-PF)."""
        try:
            await self._start_seq(thr, win)
            segs = self._burst_segs(thr, win, tail_words=2 * win)
            await self._schedule(segs, win)
        except (TrialTimeout, EsrcStrobeTimeout) as exc:
            self.chk.obs("PF", thr=thr, win=win, windows=thr, reason=f"timeout:{exc}")
            return
        sm = await self._rd(ESRC_MAIN_SM_STATUS)
        cnt = (await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)) & M_ANY
        self.chk.obs(
            "PF", thr=thr, win=win, windows=thr, alert=int(sm & M_ALERT != 0), any_fail=cnt
        )

    async def _block_disable(self) -> None:
        win = self.plan.window[0]
        try:
            await self._start_seq(0, win)
        except TrialTimeout as exc:
            self.disable_result = {"win": win, "reason": f"timeout:{exc.what} bound={exc.bound}"}
            return
        open_graded_window(TEST, self.logger)
        self.noise.byte_check(True)
        c0, mm0 = self.noise.byte_control()
        segs = self._burst_segs(DISABLE_WINDOWS, win)
        task = cocotb.start_soon(self._schedule(segs, win))
        alert = pf = 0
        peak = 0
        polls = 0
        while not task.done():
            a, f, cnt = await self._poll_triple()
            alert |= a
            pf |= f
            peak = max(peak, cnt)
            polls += 1
        timeout = None
        try:
            await task
        except EsrcStrobeTimeout as exc:
            timeout = f"timeout:strobes bound={exc.bound}"
        a, f, cnt = await self._poll_triple()
        alert |= a
        pf |= f
        peak = max(peak, cnt)
        close_graded_window(self.logger)
        self.noise.set_lanes(list(self.plan.balanced))
        c1, mm1 = self.noise.byte_control()
        self.noise.byte_check(False)
        self.chk.ctrl("NOISE-BYTES", mm1 == mm0 and c1 > c0, compared=c1 - c0, mismatched=mm1 - mm0)
        self.disable_result = {
            "alert": int(alert),
            "pf": int(pf),
            "peak": peak,
            "polls": polls,
            "win": win,
        }
        if timeout:
            self.disable_result["reason"] = timeout

    # --- grading -----------------------------------------------------------------------
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
            "failing_windows": blk.thr - 2,
            "alert": nt.get("alert"),
            "pf": nt.get("pf"),
            "any_fail_peak": nt.get("peak"),
            "any_fail_after": nt.get("after"),
        }
        if blk.start_timeout:
            fields["reason"] = blk.start_timeout
        elif nt.get("timeout"):
            fields["reason"] = nt["timeout"]
        elif not nt.get("zero"):
            fields["reason"] = "timeout:count_zero"
            fields["bound"] = nt.get("bound")
        self.chk.ok(
            "PF-NOTRIP", nt.get("alert") == 0 and nt.get("pf") == 0 and nt.get("zero"), **fields
        )
        cs = blk.consec or {}
        self.chk.ctrl("PF-CONSEC", tripped, thr=blk.thr, ctrl_single_burst_alert=int(tripped))
        fields = {
            "thr": blk.thr,
            "bursts": [blk.thr - 2, blk.thr - 2],
            "gap": self.plan.gap[blk.thr],
            "alert": cs.get("alert"),
            "pf": cs.get("pf"),
            "any_fail_after": cs.get("after"),
            "ctrl_single_burst_alert": int(tripped),
        }
        if blk.start_timeout:
            fields["reason"] = blk.start_timeout
        elif cs.get("timeout"):
            fields["reason"] = cs["timeout"]
        elif not cs.get("zero"):
            fields["reason"] = "timeout:count_zero"
            fields["bound"] = cs.get("bound")
        self.chk.ok(
            "PF-CONSEC", cs.get("alert") == 0 and cs.get("pf") == 0 and cs.get("zero"), **fields
        )

    def _grade_trip_and_disable(self) -> None:
        plan = self.plan
        ctrl = self.trip_results.get(3, {})
        ctrl_ok = bool(ctrl.get("alert"))
        self.chk.ctrl("PF-TRIP", ctrl_ok, ctrl_thr3_trip=int(ctrl_ok))
        res = self.trip_results.get(plan.t_d, {})
        any_fail = res.get("any_fail")
        fields = {
            "thr": plan.t_d,
            "win": plan.window[plan.t_d],
            "failing_windows": res.get("failing_windows"),
            "any_fail": any_fail,
            "alert": res.get("alert"),
            "pf": res.get("pf"),
            "ctrl_thr3_trip": int(ctrl_ok),
        }
        if not res.get("alert"):
            fields["reason"] = res.get("reason", "timeout:alert")
            fields["bound"] = res.get("bound")
        self.chk.ok(
            "PF-TRIP",
            bool(res.get("alert"))
            and bool(res.get("pf"))
            and any_fail is not None
            and any_fail >= plan.t_d,
            **fields,
        )
        d = self.disable_result or {}
        self.chk.ctrl("PF-DISABLE", ctrl_ok, ctrl_thr3_alert=int(ctrl_ok))
        extra = {"reason": d["reason"]} if d.get("reason") else {}
        self.chk.ok(
            "PF-DISABLE",
            not d.get("reason")
            and d.get("alert") == 0
            and d.get("pf") == 0
            and d.get("peak", 0) > DISABLE_WINDOWS - 2,
            **extra,
            thr=0,
            win=d.get("win"),
            failing_windows=DISABLE_WINDOWS,
            alert=d.get("alert"),
            pf=d.get("pf"),
            any_fail=d.get("peak"),
            ctrl_thr3_alert=int(ctrl_ok),
        )
