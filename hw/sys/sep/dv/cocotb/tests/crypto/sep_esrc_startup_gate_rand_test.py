# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC boot gate, idle hold and the restart of startup testing by MODULE_ENABLE.

Contract:
  * ``CTRL.MODULE_ENABLE`` starts startup health testing, and clearing it holds
    the main state machine idle
    (``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc:112``,
    ``MAIN_SM_STATUS.IDLE`` at ``:412``).
  * ``MAIN_SM_STATUS.BOOT_PHASE_DONE`` reports a passing startup window and
    permits entropy output (``entropy_source.adoc:409``). The boot gate qualifies
    the whitener input, the uncompressed-byte path and the BIW observe FIFO; the
    32-bit health test sees the stream ungated
    (``hw/ip/entropy_source/doc/architecture.adoc:40-43``;
    ``BIW_OBS_CTRL.RAW_ENABLE`` at ``entropy_source.adoc:792``).
  * ``SHA256_STATUS.BUSY`` is set while SHA-256 processing or digest output is
    active (``entropy_source.adoc:209``).
  * ``HEALTH_TEST_STATUS`` bit 0 latches a 32-bit stream repetition failure
    (``hw/ip/entropy_source/regs/entropy_source.rdl:352``).
  * The five total-failure counters count since the last ``MODULE_ENABLE``
    rising edge (``entropy_source.rdl:821-861``), and the rising edge restarts
    startup health testing (``architecture.adoc:226-227``).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20: the TRNG domain runs, the
Key Manager and every engine stay in reset. The noise model drives
``esrc_noise_ext_i`` from before the first TRNG reset release to the end of the
leaf (``env/sep_esrc_pattern_noise.py``); every start writes
``DECORRELATOR_CTRL.BYPASS`` on all lanes, so each lane byte is the held bit.

Start: TRNG reset; ``MODULE_ENABLE`` = 0; ``ALERT_THRESHOLD`` = 0, BYPASS, the
clean limits of the reset window 2048, ``BIW_OBS_CTRL.RAW_ENABLE``; the noise of
the leg; ``MODULE_ENABLE`` = 1 at t0. With ``balanced`` on every lane the startup
window passes by construction; with stuck0 it fails. A poll reads
``BIW_OBS_STATUS.LEVEL``, ``FIFO_STATUS.LEVEL`` and ``MAIN_SM_STATUS`` back to back.

Randomization (``SepSeededRng`` from the run seed, drawn before any stimulus):
the ``balanced`` masks and permutation, the order of the three toggle moments,
the fall instant of each moment (a fraction of the clean boot time of the same
seed) and the ``RAW_ENABLE`` value of each toggle leg.

Checkers:
  CHK-BOOT-CLEAN    every poll with a level above 0 reads BOOT_PHASE_DONE = 1.
                    Control: both levels rise after the gate opens.
  CHK-BOOT-BAD      stuck0 start, hold of 3 t_boot: BOOT_PHASE_DONE 0, both
                    levels 0, no strobe on ``esrc_whiten_push_o`` or
                    ``esrc_compress_vld_o``, HEALTH_TEST_STATUS bit 0 = 1.
                    Control: the clean start shows levels and tap strobes.
  CHK-BOOT-IDLE     after MODULE_ENABLE = 0: IDLE = 1, and after BUSY = 0 and a
                    drain the FIFO stays empty and the stream tap silent for
                    3 t_fill. Control: IDLE 0 and a level above 0 before.
  CHK-BOOT-RESTART  after the rise every counter that read non-zero before the
                    fall reads 0 at once, and BOOT_PHASE_DONE returns to 1.
                    Control: REPCNT_TOTAL_FAILS read non-zero before.
  CHK-BOOT-TOGGLE   per drawn moment (boot, after_boot, bad_pattern): IDLE = 1
                    after the fall; after the rise every counter that read
                    non-zero before the fall reads 0 at once, and
                    BOOT_PHASE_DONE returns to 1. Failures after the rise count
                    again by contract (stuck samples still in the pipeline at
                    the bad_pattern moment), so the counters at BOOT_PHASE_DONE
                    are logged as OBS-BOOT-COUNTERS only.
                    Control: IDLE 0 before the fall; the boot moment reads
                    BOOT_PHASE_DONE 0 last; bad_pattern reads REPCNT above 0.
Every bound is a multiple of a clean time of the same seed and is logged.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_esrc_pattern_noise import (
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
    ESRC_ALERT_THRESHOLD,
    ESRC_APT_PROPORTION_1BIT,
    ESRC_APT_PROPORTION_LO,
    ESRC_BIW_OBS_CTRL,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_FIFO_RDATA,
    ESRC_FIFO_STATUS,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HEALTH_TEST_STATUS,
    ESRC_HEALTH_TEST_WINDOW_SIZE,
    ESRC_MAIN_SM_STATUS,
    ESRC_MARKOV_TEST_PROB_THRESHOLDS,
)
from seq_lib.sep_esrc_clean_start_seq import (
    BYPASS_ALL,
    LATENCY_FACTOR,
    SepEsrcCleanStart,
    SepEsrcLeafSetup,
    clean_limits,
)

TEST = "sep_esrc_startup_gate_rand_test"

WINDOW = 2048
NUM_LANES = 12
MOMENTS = ("boot", "after_boot", "bad_pattern")
BASELINE_PARK = ("otbn", "aes", "hmac", "kmac", "abr")

ESRC_BIW_OBS_STATUS = sym("ENTROPY_SOURCE_BIW_OBS_STATUS_REG_ADDR")
ESRC_SHA256_STATUS = sym("ENTROPY_SOURCE_SHA256_STATUS_REG_ADDR")
TOTALS = (
    ("rep", "REPCNT_TOTAL_FAILS"),
    ("apt_hi", "APT_HI_TOTAL_FAILS"),
    ("apt_lo", "APT_LO_TOTAL_FAILS"),
    ("mkv_hi", "MARKOV_HI_TOTAL_FAILS"),
    ("mkv_lo", "MARKOV_LO_TOTAL_FAILS"),
)
TOTAL_ADDR = {k: sym(f"ENTROPY_SOURCE_{r}_REG_ADDR") for k, r in TOTALS}
TOTAL_REG = dict(TOTALS)


def _fm(reg: str, field: str) -> tuple[int, int]:
    meta = ENTROPY_SOURCE.fields(reg)[field]
    return meta["bm"], meta["bp"]


def _fld(reg: str, field: str, value: int) -> int:
    bm, bp = _fm(reg, field)
    return (value & bm) >> bp


SM_IDLE, _ = _fm("MAIN_SM_STATUS", "IDLE")
SM_BOOT, _ = _fm("MAIN_SM_STATUS", "BOOT_PHASE_DONE")
SHA_BUSY, _ = _fm("SHA256_STATUS", "BUSY")

# Outer caps of a first latency measurement: a cap, never a contract.
FIRST_LATENCY_CAP = 20_000
HOLD_FACTOR = 3
MAX_POPS = 4 * 64
PRE_CLEAN_MAX = 16


@dataclass(frozen=True)
class Plan:
    seed: int
    balanced: tuple[Balanced, ...]
    order: tuple[str, ...]
    boot_pm: int
    after_boot_pm: int
    bad_pattern_pm: int
    raw: tuple[int, int, int]

    def describe(self) -> str:
        return (
            f"order={','.join(self.order)} boot_fall_pm={self.boot_pm} "
            f"after_boot_delay_pm={self.after_boot_pm} bad_pattern_delay_pm={self.bad_pattern_pm} "
            f"raw_enable={list(self.raw)} window={WINDOW} {describe(self.balanced)}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    balanced = tuple(balanced_lanes(rng))
    order = list(MOMENTS)
    rng.shuffle(order)
    # Fractions in per mille of the clean t_boot of the same seed; scaled at run time.
    boot_pm = rng.randrange(0, 500)
    after_boot_pm = rng.randrange(0, 1001)
    bad_pattern_pm = rng.randrange(0, 1001)
    raw = (rng.getrandbits(1), rng.getrandbits(1), rng.getrandbits(1))
    return Plan(seed, balanced, tuple(order), boot_pm, after_boot_pm, bad_pattern_pm, raw)


class _Esrc(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


@dataclass
class Poll:
    biw: int
    fifo: int
    sm: int
    clk: int

    @property
    def done(self) -> int:
        return _fld("MAIN_SM_STATUS", "BOOT_PHASE_DONE", self.sm)

    @property
    def idle(self) -> int:
        return _fld("MAIN_SM_STATUS", "IDLE", self.sm)


@pyuvm.test()
class sep_esrc_startup_gate_rand_test(sep_base_test):
    """Boot gate on clean and failing starts, idle hold, counter restart, three toggles."""

    required_evidence = (
        "CHK-BOOT-CLEAN",
        "CHK-BOOT-BAD",
        "CHK-BOOT-IDLE",
        "CHK-BOOT-RESTART",
        "CHK-BOOT-TOGGLE",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=BASELINE_PARK)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.plan = plan
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        self.chk = SepChkLog(self, TEST, seed)
        self.esrc = _Esrc(self)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.whiten = SepBitWatch(dut.esrc_whiten_push_o, name="esrc_whiten_push_o").start()
        self.vld = SepBitWatch(dut.esrc_compress_vld_o, name="esrc_compress_vld_o").start()
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        # The noise runs from before the first TRNG reset release (the testers run from it).
        self.noise.start(list(plan.balanced))
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)
        self.idle_clean: int | None = None
        self.t_boot = 0
        self.t_fill = 0
        self.ctrl_whiten = 0
        self.ctrl_vld = 0
        self.ctrl_fifo_max = 0
        self.ctrl_biw_max = 0

        # A set-up or strobe wait that times out inside a leg fails the check of that
        # leg (reason=timeout) and the leaf goes on with the next leg.
        await self._guard(self._clean_leg(), "BOOT-CLEAN")
        await self._guard(self._idle_leg(), "BOOT-IDLE")
        await self._guard(self._bad_leg(), "BOOT-BAD")
        await self._guard(self._restart_leg(), "BOOT-RESTART")
        for i, moment in enumerate(plan.order):
            await self._guard(self._toggle_leg(moment, plan.raw[i]), "BOOT-TOGGLE", moment=moment)
        close_graded_window(self.logger)

        self.noise.byte_check(False)
        await self.noise.stop()
        await self.whiten.stop()
        await self.vld.stop()
        await self.clk.stop()
        self.chk.finish()

    async def _guard(self, coro, check: str, **fields) -> None:
        """Run one leg; a set-up or strobe timeout fails ``check`` with the reason."""
        try:
            await coro
        except (TrialTimeout, EsrcStrobeTimeout) as exc:
            close_graded_window(self.logger)
            self.noise.byte_check(False)
            what = exc.what if isinstance(exc, TrialTimeout) else "strobes"
            self.chk.ok(check, False, reason=f"timeout:{what}", bound=exc.bound, **fields)

    # --- bus, polls, waits -----------------------------------------------------
    def _now(self) -> int:
        return self.clk.clk

    async def _rd(self, addr: int) -> int:
        return await self.esrc._rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.esrc._wr(addr, data)

    async def _poll(self) -> Poll:
        biw = await self._rd(ESRC_BIW_OBS_STATUS)
        fifo = await self._rd(ESRC_FIFO_STATUS)
        sm = await self._rd(ESRC_MAIN_SM_STATUS)
        return Poll(
            _fld("BIW_OBS_STATUS", "LEVEL", biw),
            _fld("FIFO_STATUS", "LEVEL", fifo),
            sm & ENTROPY_SOURCE.mask("MAIN_SM_STATUS"),
            self._now(),
        )

    async def _sm(self) -> int:
        return await self._rd(ESRC_MAIN_SM_STATUS)

    async def _fifo_level(self) -> int:
        return _fld("FIFO_STATUS", "LEVEL", await self._rd(ESRC_FIFO_STATUS))

    async def _enable(self, value: int) -> None:
        await self._wr(ESRC_CTRL, ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=value))

    async def _totals(self) -> dict[str, int]:
        out = {}
        for key, reg in TOTALS:
            out[key] = _fld(reg, "FAIL_COUNT", await self._rd(TOTAL_ADDR[key]))
        return out

    @staticmethod
    def _fmt_totals(t: dict[str, int] | None) -> str:
        if t is None:
            return "na"
        return "_".join(str(t[k]) for k, _ in TOTALS)

    async def _drain(self) -> bool:
        """Pop FIFO_RDATA until FIFO_STATUS.LEVEL reads 0 (pops only a non-empty FIFO)."""
        pops = 0
        while pops <= MAX_POPS:
            level = await self._fifo_level()
            if level == 0:
                return True
            for _ in range(level):
                await self._rd(ESRC_FIFO_RDATA)
                pops += 1
        return False

    async def _wait_idle(self, what: str) -> tuple[bool, int, int]:
        """Poll MAIN_SM_STATUS.IDLE to 1. Returns (matched, clocks, bound)."""
        bound = (
            FIRST_LATENCY_CAP
            if self.idle_clean is None
            else LATENCY_FACTOR * max(1, self.idle_clean)
        )
        t = self._now()
        ok, samples = await poll_until(self._sm, self._now, SM_IDLE, SM_IDLE, bound)
        clocks = (samples[-1][0] if samples else self._now()) - t
        if ok and self.idle_clean is None:
            self.idle_clean = max(1, clocks)
        self.logger.info("%s idle ok=%d clk=%d bound=%d", what, ok, clocks, bound)
        return ok, clocks, bound

    async def _wait_done(self, bound: int) -> tuple[bool, int]:
        """Poll BOOT_PHASE_DONE to 1 within ``bound`` clocks. Returns (matched, clocks)."""
        t = self._now()
        ok, samples = await poll_until(self._sm, self._now, SM_BOOT, SM_BOOT, bound)
        return ok, (samples[-1][0] if samples else self._now()) - t

    # --- noise lane-byte control -------------------------------------------------
    def _bytes_begin(self) -> tuple[int, int]:
        self.noise.byte_check(True)
        return self.noise.byte_control()

    def _bytes_end(self, leg: str, base: tuple[int, int]) -> None:
        c, mm = self.noise.byte_control()
        dc, dm = c - base[0], mm - base[1]
        self.chk.ctrl("NOISE-BYTES", dm == 0 and dc > 0, leg=leg, compared=dc, mismatched=dm)
        self.noise.byte_check(False)

    # --- reset and starts -----------------------------------------------------------
    async def _trng_reset(self) -> int:
        """SW_RESET_N TRNG bit 0 then 1 (SepEsrcLeafSetup). Returns the release mark."""
        close_graded_window(self.logger)
        self.noise.byte_check(False)
        return await self.setup.trng_reset()

    async def _clean_start(self, raw: int) -> int:
        """Reset sequence and clean start with ``balanced``; returns t0 (clock of the enable)."""
        mark = await self._trng_reset()
        open_graded_window(TEST, self.logger)
        cs = SepEsrcCleanStart(
            self,
            self.noise,
            list(self.plan.balanced),
            window=WINDOW,
            extra_writes=(
                (ESRC_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=0)),
                (ESRC_BIW_OBS_CTRL, ENTROPY_SOURCE.value("BIW_OBS_CTRL", RAW_ENABLE=raw)),
            ),
            logger=self.logger,
        )
        await cs.run(release_mark=mark)
        return self._now()

    async def _bad_start(self) -> tuple[int, object, object]:
        """Reset sequence and a stuck0 start; returns (t0, whiten mark, stream mark)."""
        mark = await self._trng_reset()
        open_graded_window(TEST, self.logger)
        lim = clean_limits(WINDOW)
        await self._enable(0)
        await self._wr(
            ESRC_DECORRELATOR_CTRL, ENTROPY_SOURCE.value("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL)
        )
        await self._wr(
            ESRC_HEALTH_TEST_WINDOW_SIZE,
            ENTROPY_SOURCE.value("HEALTH_TEST_WINDOW_SIZE", SIZE=lim.window),
        )
        await self._wr(
            ESRC_APT_PROPORTION_1BIT,
            ENTROPY_SOURCE.value("APT_PROPORTION_1BIT", LIMIT=lim.apt_1bit),
        )
        await self._wr(
            ESRC_APT_PROPORTION_LO, ENTROPY_SOURCE.value("APT_PROPORTION_LO", LIMIT=lim.apt_lo)
        )
        await self._wr(
            ESRC_MARKOV_TEST_PROB_THRESHOLDS,
            ENTROPY_SOURCE.value(
                "MARKOV_TEST_PROB_THRESHOLDS",
                PROB_01_THRESHOLD=lim.prob_01,
                PROB_10_THRESHOLD=lim.prob_10,
            ),
        )
        await self._wr(
            ESRC_HEALTH_TEST_CTRL,
            ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", REPETITION_LIMIT=lim.repetition),
        )
        await self._wr(ESRC_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=0))
        await self._wr(ESRC_BIW_OBS_CTRL, ENTROPY_SOURCE.value("BIW_OBS_CTRL", RAW_ENABLE=1))
        # MODULE_ENABLE = 0 here, so the immediate change applies stuck0 from the first sample.
        self.noise.set_lanes([Stuck(0)] * NUM_LANES, immediate=True)
        pre = self.noise.words_since(mark)
        self.logger.info("ESRC-BAD-START %s pre_clean_strobes=%d", lim.describe(), pre)
        if pre > PRE_CLEAN_MAX:
            raise AssertionError(f"pre_clean_strobes={pre} above {PRE_CLEAN_MAX}")
        wm, vm = self.whiten.mark(), self.vld.mark()
        await self._enable(1)
        return self._now(), wm, vm

    # --- legs -------------------------------------------------------------------------
    async def _clean_leg(self) -> None:
        """Clean start: the gate rule at every poll, t_boot, t_fill and the tap counts."""
        wm, vm = self.whiten.mark(), self.vld.mark()
        t0 = await self._clean_start(1)
        base = self._bytes_begin()
        word0 = self.noise.mark()
        # Word-counted bound: the first window can be partial, so done comes within 2W + 64.
        word_bound = 2 * WINDOW + 64
        violations: list[str] = []
        viol_fifo = viol_biw = 0
        biw_max = fifo_max = 0
        t_done = None
        polls = 0
        while t_done is None:
            if self.noise.words_since(word0) > word_bound:
                # The later legs bound their waits from t_boot and t_fill: use the
                # word bounds.
                self.t_boot = word_bound * self.setup.period()
                self.t_fill = WINDOW * self.setup.period()
                self._bytes_end("clean_boot", base)
                raise TrialTimeout("boot_done", word_bound * self.setup.period())
            p = await self._poll()
            polls += 1
            biw_max, fifo_max = max(biw_max, p.biw), max(fifo_max, p.fifo)
            if (p.biw or p.fifo) and not p.done:
                viol_fifo += int(p.fifo > 0)
                viol_biw += int(p.biw > 0)
                violations.append(f"clk{p.clk - t0}:biw{p.biw}:fifo{p.fifo}")
            if p.done:
                t_done = p.clk
        self.t_boot = max(1, t_done - t0)
        self._bytes_end("clean_boot", base)
        # Keep polling until both levels read above 0 (bounded: one more window of words).
        word1 = self.noise.mark()
        fill_bound = WINDOW
        t_fifo = None
        both = False
        while not both and self.noise.words_since(word1) <= fill_bound:
            p = await self._poll()
            polls += 1
            biw_max, fifo_max = max(biw_max, p.biw), max(fifo_max, p.fifo)
            if (p.biw or p.fifo) and not p.done:
                viol_fifo += int(p.fifo > 0)
                viol_biw += int(p.biw > 0)
                violations.append(f"clk{p.clk - t0}:biw{p.biw}:fifo{p.fifo}")
            if p.fifo and t_fifo is None:
                t_fifo = p.clk
            both = p.biw > 0 and p.fifo > 0
        self.t_fill = max(1, (t_fifo or self._now()) - t_done)
        self.ctrl_whiten = self.whiten.high_clocks_since(wm)
        self.ctrl_vld = self.vld.high_clocks_since(vm)
        self.ctrl_fifo_max, self.ctrl_biw_max = fifo_max, biw_max
        self.logger.info(
            "CLEAN-START t_boot=%d t_fill=%d polls=%d whiten_push=%d stream_vld=%d",
            self.t_boot,
            self.t_fill,
            polls,
            self.ctrl_whiten,
            self.ctrl_vld,
        )
        self.chk.ctrl(
            "BOOT-CLEAN",
            both,
            fifo_level_max=fifo_max,
            biw_obs_level_max=biw_max,
            fill_bound_words=fill_bound,
        )
        self.chk.ctrl(
            "BOOT-TAPS", self.ctrl_whiten > 0, tap="esrc_whiten_push_o", n=self.ctrl_whiten
        )
        self.chk.ctrl("BOOT-TAPS", self.ctrl_vld > 0, tap="esrc_compress_vld_o", n=self.ctrl_vld)
        self.chk.ok(
            "BOOT-CLEAN",
            not violations,
            boot_done_clk=self.t_boot,
            fifo_gt0_implies_done=int(viol_fifo == 0),
            biw_obs_gt0_implies_done=int(viol_biw == 0),
            fifo_level_max=fifo_max,
            biw_obs_level_max=biw_max,
            violations=",".join(violations[:8]) or "none",
        )
        await self.setup.measure_period(self.chk)

    async def _idle_leg(self) -> None:
        """MODULE_ENABLE = 0 after the clean start: IDLE, then no new FIFO word for 3 t_fill."""
        level_before = await self._fifo_level()
        drained0 = await self._drain()
        idle_before = _fld("MAIN_SM_STATUS", "IDLE", await self._sm())
        self.chk.ctrl(
            "BOOT-IDLE",
            idle_before == 0 and level_before > 0 and drained0,
            idle_before=idle_before,
            level_before=level_before,
            drained=drained0,
        )
        await self._enable(0)
        idle_ok, idle_clk, idle_bound = await self._wait_idle("idle_leg")
        reason = "" if idle_ok else f"timeout:idle bound={idle_bound}"
        busy_ok = False
        if idle_ok:
            busy_ok, _ = await poll_until(
                lambda: self._rd(ESRC_SHA256_STATUS), self._now, SHA_BUSY, 0, FIRST_LATENCY_CAP
            )
            if not busy_ok:
                reason = f"timeout:sha_busy bound={FIRST_LATENCY_CAP}"
        drained = await self._drain() if busy_ok else False
        if busy_ok and not drained:
            reason = f"drain_not_empty pops={MAX_POPS}"
        hold = HOLD_FACTOR * self.t_fill
        levels: list[int] = []
        stream = None
        if drained:
            vm = self.vld.mark()
            t = self._now()
            while self._now() - t < hold:
                levels.append(await self._fifo_level())
            stream = self.vld.high_clocks_since(vm)
        stable = bool(levels) and all(v == 0 for v in levels)
        fields = {
            "idle_before": idle_before,
            "idle": int(idle_ok),
            "idle_clk": idle_clk,
            "sha_busy_clear": int(busy_ok),
            "level_before": level_before,
            "level_stable": int(stable),
            "stream_vld": stream if stream is not None else "na",
            "hold_clk": hold,
            "polls": len(levels),
            "ctrl_stream_vld": self.ctrl_vld,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("BOOT-IDLE", idle_ok and busy_ok and stable and stream == 0, **fields)

    async def _bad_leg(self) -> None:
        """Stuck0 start: for 3 t_boot no gate, no level, no tap strobe; HT status bit 0 set."""
        t0, wm, vm = await self._bad_start()
        base = self._bytes_begin()
        window = HOLD_FACTOR * self.t_boot
        done_seen = biw_seen = fifo_seen = 0
        polls = 0
        while self._now() - t0 < window:
            p = await self._poll()
            polls += 1
            done_seen |= p.done
            biw_seen = max(biw_seen, p.biw)
            fifo_seen = max(fifo_seen, p.fifo)
        push = self.whiten.high_clocks_since(wm)
        stream = self.vld.high_clocks_since(vm)
        ht = await self._rd(ESRC_HEALTH_TEST_STATUS)
        ht_bit0 = _fld("HEALTH_TEST_STATUS", "HEALTH_STATUS", ht) & 1
        self._bytes_end("bad_start", base)
        self.chk.ok(
            "BOOT-BAD",
            done_seen == 0
            and biw_seen == 0
            and fifo_seen == 0
            and push == 0
            and stream == 0
            and ht_bit0 == 1,
            window_clk=window,
            polls=polls,
            boot_done=done_seen,
            fifo_level=fifo_seen,
            biw_obs_level=biw_seen,
            whiten_push=push,
            stream_vld=stream,
            ht_status_bit0=ht_bit0,
            rsvd=f"0x{ht & ~ENTROPY_SOURCE.mask('HEALTH_TEST_STATUS') & 0xFFFFFFFF:x}",
            ctrl_fifo_level_max=self.ctrl_fifo_max,
            ctrl_biw_obs_level_max=self.ctrl_biw_max,
            ctrl_whiten_push=self.ctrl_whiten,
            ctrl_stream_vld=self.ctrl_vld,
        )

    async def _restart_leg(self) -> None:
        """After the bad start: the rising edge clears the counters and restarts boot."""
        before = await self._totals()
        self.chk.ctrl("BOOT-RESTART", before["rep"] > 0, rep_before=before["rep"])
        base = self._bytes_begin()
        self.noise.set_lanes(list(self.plan.balanced))
        await self.noise.wait_words(2, LATENCY_FACTOR * self.t_boot)
        await self._enable(0)
        idle_ok, _, idle_bound = await self._wait_idle("restart_leg")
        after_fall = await self._totals()
        self.chk.obs("BOOT-COUNTERS", leg="restart", after_fall=self._fmt_totals(after_fall))
        await self._enable(1)
        after_edge = await self._totals()
        done_ok, done_clk = await self._wait_done(HOLD_FACTOR * self.t_boot)
        self._bytes_end("restart_boot", base)
        nonzero = [k for k, _ in TOTALS if before[k] and after_edge[k]]
        fields = {
            "boot_done_again": int(done_ok),
            "done_clk": done_clk,
            "total_fails_before": self._fmt_totals(before),
            "total_fails_after_edge": self._fmt_totals(after_edge),
            "rep_before_nonzero": int(before["rep"] > 0),
            "nonzero_after_edge": len(nonzero),
        }
        if not idle_ok:
            fields["reason"] = f"timeout:idle bound={idle_bound}"
        elif not done_ok:
            fields["reason"] = f"timeout:boot_done bound={HOLD_FACTOR * self.t_boot}"
        self.chk.ok("BOOT-RESTART", idle_ok and done_ok and not nonzero, **fields)

    async def _toggle_leg(self, moment: str, raw: int) -> None:
        """One fall moment with clean noise, then a rise: IDLE, restart, counters cleared."""
        plan = self.plan
        dut = cocotb.top
        t0 = await self._clean_start(raw)
        base = self._bytes_begin()
        done_bound = HOLD_FACTOR * self.t_boot
        reason = ""
        idle_before = None
        last_done = None
        before: dict[str, int] | None = None
        if moment == "boot":
            instant = plan.boot_pm * self.t_boot // 1000
            seen_running = False
            sm = 0
            while True:
                sm = await self._sm()
                seen_running = seen_running or not (sm & SM_IDLE)
                if seen_running and self._now() - t0 >= instant:
                    break
                if self._now() - t0 > done_bound:
                    reason = f"timeout:running bound={done_bound}"
                    break
            idle_before = _fld("MAIN_SM_STATUS", "IDLE", sm)
            last_done = _fld("MAIN_SM_STATUS", "BOOT_PHASE_DONE", sm)
            self.chk.ctrl(
                "BOOT-TOGGLE",
                idle_before == 0 and last_done == 0,
                moment=moment,
                idle_before=idle_before,
                last_done=last_done,
                fall_clk=self._now() - t0,
            )
            before = await self._totals()
        else:
            ok, _ = await self._wait_done(done_bound)
            if not ok:
                reason = f"timeout:boot_done bound={done_bound}"
            if moment == "bad_pattern" and not reason:
                self.noise.set_lanes([Stuck(0)] * NUM_LANES)
                rep_seen = 0
                t = self._now()
                while self._now() - t <= done_bound:
                    rep_seen = _fld(
                        TOTAL_REG["rep"], "FAIL_COUNT", await self._rd(TOTAL_ADDR["rep"])
                    )
                    if rep_seen:
                        break
                self.chk.ctrl(
                    "BOOT-TOGGLE",
                    rep_seen > 0,
                    moment=moment,
                    rep_before=rep_seen,
                    bound=done_bound,
                )
            pm = plan.after_boot_pm if moment == "after_boot" else plan.bad_pattern_pm
            delay = pm * self.t_boot // 1000
            if delay:
                await ClockCycles(dut.clk_i, delay)
            before = await self._totals()
            idle_before = _fld("MAIN_SM_STATUS", "IDLE", await self._sm())
            self.chk.ctrl(
                "BOOT-TOGGLE",
                idle_before == 0,
                moment=moment,
                idle_before=idle_before,
                delay_clk=delay,
            )
        await self._enable(0)
        idle_ok, idle_clk, idle_bound = await self._wait_idle(f"toggle_{moment}")
        if not idle_ok and not reason:
            reason = f"timeout:idle bound={idle_bound}"
        # MODULE_ENABLE = 0: the immediate change returns every lane to balanced.
        self.noise.set_lanes(list(plan.balanced), immediate=True)
        await self._enable(1)
        # REPCNT_TOTAL_FAILS is read first, before the first strobe after the rise;
        # the window counters fail only at a window end, a whole window later.
        after = await self._totals()
        done_ok, _ = await self._wait_done(done_bound)
        if not done_ok and not reason:
            reason = f"timeout:boot_done_again bound={done_bound}"
        at_done = await self._totals()
        self.chk.obs(
            "BOOT-COUNTERS", leg=f"toggle_{moment}", at_boot_done=self._fmt_totals(at_done)
        )
        self._bytes_end(f"toggle_{moment}", base)
        nonzero = [k for k, _ in TOTALS if before and before[k] and after[k]]
        fields = {
            "moment": moment,
            "raw_enable": raw,
            "idle_before": idle_before,
            "idle_clk": idle_clk,
            "boot_done_again": int(done_ok),
            "rep_before": before["rep"] if before else "na",
            "total_fails_before": self._fmt_totals(before),
            "total_fails_after_rise": self._fmt_totals(after),
            "nonzero_after_rise": len(nonzero),
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "BOOT-TOGGLE",
            not reason and idle_ok and done_ok and not nonzero,
            **fields,
        )
