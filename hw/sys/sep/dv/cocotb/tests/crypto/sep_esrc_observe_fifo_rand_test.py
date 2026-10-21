# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC noise and BIW observe FIFOs: ungated capture, lane select, flush, overflow, lock.

Contract (``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc``, ``NOISE_OBS_CTRL``,
``NOISE_OBS_STATUS``, ``NOISE_OBS_RDATA``, ``BIW_OBS_CTRL``, ``BIW_OBS_STATUS``,
``INTR_STATUS``, ``FIPS_LOCK``; ``hw/ip/entropy_source/doc/architecture.adoc``,
Entropy Source):
  * The noise observe FIFO sees the stream before the boot gate; the BIW observe
    FIFO captures after startup (architecture.adoc:42-43, :182, :186).
  * ``LANE_SEL`` 0 to 11 selects the lane, other values select lane 0, and a lane
    change flushes (entropy_source.adoc:825). A word holds 32 LSB-first
    pre-decorrelator samples of the selected lane (entropy_source.adoc:851).
  * A ``FLUSH`` write discards the buffered words (entropy_source.adoc:827).
  * A word offered while full is discarded and sets ``NOISE_OBS_OVERFLOW`` or
    ``BIW_OBS_OVERFLOW``, which clear by write-one (entropy_source.adoc:134, :136).
  * ``FIPS_LOCK.LOCK`` prevents changes of both ``RAW_ENABLE`` fields
    (entropy_source.adoc:752, :792, :828; architecture.adoc:239-241).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20. Every set-up selects the
external sample clock on every lane, so the stuck-at values reach the noise
observe samples on both simulators. A lane value z is applied through the ESRC
noise-source stuck-at inject (``esrc_noise_stuck_en_i``/``esrc_noise_stuck_val_i``,
docs/SEP_TB_ARCH.adoc) and, with the same value, through ``esrc_noise_ext_i``; the
inject is released at each set-up and at the end of the leaf.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the order of the 16 ``LANE_SEL`` values (every write changes the
effective lane), z per lane change (both values, z = 1 at least once), the flush
lane, its z and the words f before the flush, the words k at the lock moment,
z of each lock pass, and the lane and bits of the sample-clock sequence leg.

Sample-clock sequence leg (``hw/ip/entropy_source/doc/architecture.adoc:75``: a
flop on the sampling clock, then a two-stage synchronizer into ``clk_i``). The
lane divides its sample clock by 1 (``GENERATOR_<lane>_SAMPLE_CLK_CONFIG`` = 0),
so its sampling flop takes each rising edge of ``entropy_rosc_sample_clk_i``.
The leaf stops that clock, sets ``RAW_ENABLE`` 1 on the lane, then restarts the
clock at ``8 x clk_i + 2 ps`` (not a multiple of the ``clk_i`` period), so the
first sample edge after the restart is bit 0 of the first word. Every sample edge
lies 150 ps or more from each ``clk_i`` edge. The stuck-at inject drives bit k of
the sequence for sample edge k: the leaf writes it after edge k - 1, and the
inject takes it at the next ``clk_i`` falling edge, before edge k. The leaf stops
the clock after the last edge. Sequence: 5 words of seeded bits, with bit 8 of
each word the complement of bit 7 (the named pair ``SEQ_PAIR``) and bit 159 the
complement of bit 158, so a single lost or repeated sample among samples 0 to 158
changes a graded bit or the word count.

Checkers:
  CHK-OBS-UNGATED   failing startup: BOOT_PHASE_DONE 0 and noise LEVEL > 0; control:
                    BIW LEVEL 0 in the same trial.
  CHK-OBS-LANE      LEVEL falls at an effective lane change; words 2 to 8 of the change
                    equal the lane value.
  CHK-OBS-PACK      the first word after each lane change equals the lane value in all
                    32 bits.
  CHK-OBS-FLUSH     no word from before a FLUSH or a lane change is popped after it.
  CHK-OBS-OVERFLOW  plateau D, overflow bit 1, LEVEL D after two fill times, W1C clears.
                    Control: the overflow bit reads 0 before the leg and 1 after
                    the drain, before the write-one.
  CHK-OBS-LOCK      locked at 1: L + 2 words delivered, last two noise words equal the
                    lane value; a FLUSH with old words of z and words of 1 - z buffered
                    lowers LEVEL, and every word popped after it equals the word of
                    1 - z (no kept word); locked at 0: LEVEL stays 0.
  CHK-OBS-OFF       both RAW_ENABLE fields 0, the module running after the boot phase:
                    both LEVELs read 0 after a hold of 256 strobes and at least 4 x
                    the measured first-word time of each FIFO (entropy_source.adoc:792,
                    :828: ``RAW_ENABLE`` enables the capture).
                    Control: both fields and both LEVELs read 0 before the hold.
  CHK-OBS-SEQ       sample-clock sequence leg: LEVEL is 5 after the last edge, and word w
                    equals sequence bits 32w to 32w + 31, LSB first (entropy_source.adoc:851;
                    one sample per sample edge, architecture.adoc:75).
                    Controls: divide 0 and external clock on the lane, LEVEL 0 and
                    RAW_ENABLE 1 before the first edge, the lane's synchronized bit holds
                    the preamble value.
  CHK-SYNC-DEPTH    same leg: at each sample edge k, counted in cocotb on ``clk_i``
                    rising edges, ``esrc_noise_bit_o[lane]`` (``u_noise_source.noise_o``)
                    equals bit k at the 2nd ``clk_i`` rising edge after the edge, and
                    still holds the previous bit at the 1st where bit k differs from it
                    (architecture.adoc:75).
                    Control: every sample edge lies at least 150 ps from each ``clk_i``
                    rising and falling edge, measured.
Logged only: ``OBS-BLOCKED CHK-OBS-MAIN`` (no stated rule that observe capture leaves
the main chain rate unchanged); the main-chain leg logs its counts. ``OBS-OBS-FAST``
logs the lost and repeated samples of a 64-bit sequence at a sample period of
``2 x clk_i + 2 ps`` (no stated maximum sample rate).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Event, First, NextTimeStep, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
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
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, sym
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    ESRC_ALERT_THRESHOLD,
    ESRC_BIW_OBS_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_FIFO_CTRL,
    ESRC_FIPS_LOCK,
    ESRC_INTR_ENABLE,
    ESRC_INTR_STATUS,
    ESRC_MAIN_SM_STATUS,
    ESRC_RING_OSC_CTRL,
    ESRC_RING_OSC_ENABLE,
)
from seq_lib.sep_esrc_clean_start_seq import (
    BYPASS_ALL,
    LATENCY_FACTOR,
    SepEsrcCleanStart,
    SepEsrcLeafSetup,
)

TEST = "sep_esrc_observe_fifo_rand_test"

ESRC_NOISE_OBS_CTRL = sym("ENTROPY_SOURCE_NOISE_OBS_CTRL_REG_ADDR")
ESRC_NOISE_OBS_STATUS = sym("ENTROPY_SOURCE_NOISE_OBS_STATUS_REG_ADDR")
ESRC_NOISE_OBS_RDATA = sym("ENTROPY_SOURCE_NOISE_OBS_RDATA_REG_ADDR")
ESRC_BIW_OBS_STATUS = sym("ENTROPY_SOURCE_BIW_OBS_STATUS_REG_ADDR")
ESRC_BIW_OBS_RDATA = sym("ENTROPY_SOURCE_BIW_OBS_RDATA_REG_ADDR")

PARK = ("otbn", "aes", "hmac", "kmac", "abr")
WINDOW = 2048
LANE_SEL_VALUES = 16
# entropy_source.adoc:825: values 0 to 11 select the lane, other values lane 0.
LANE_SEL_SAME_AS_0 = (0, 12, 13, 14, 15)
LANE_SEL_LANES = tuple(range(1, NUM_LANES))
WORDS_BEFORE_CHANGE = 4
WORDS_AFTER_CHANGE = 8
FLUSH_NEW_WORDS = 2
LOCK_EXTRA_POPS = 2
LOCK_FLUSH_WORDS = 4
LOCK0_WAIT_FACTOR = 4
UNGATED_WAIT_FACTOR = 4
MAIN_WORDS = 256
# Strobes of the capture-off leg: eight observe words of 32 samples.
OFF_STROBES = 8 * 32
# The capture-off hold also spans this many first-word times of each FIFO, measured
# in the ungated trials of the same seed (test parameter).
OFF_WORD_FACTOR = 4
DRAW_TRIES = 16
FIFO_DEPTH_MAX = 64  # bound of a drain loop: the RDL LEVEL field holds at most 64 words
ALL_ONES = 0xFFFF_FFFF

# Sample-clock sequence leg (test parameters).
SCLK = "entropy_rosc_sample_clk_i"
SEQ_WORDS = 5
SEQ_BITS = 32 * SEQ_WORDS
# Word bit positions that always differ in every sequence word.
SEQ_PAIR = (7, 8)
FAST_BITS = 64
SEQ_PERIOD_CLK = 8
FAST_PERIOD_CLK = 2
# Each sample period is the clk_i multiple plus this drift, so the sample edges
# walk across the clk_i period by this step.
SAMPLE_DRIFT_PS = 2
# Offset of the first sample edge after a clk_i rising edge; the drift keeps every
# graded edge in [SAMPLE_GUARD_PS, T/2 - SAMPLE_GUARD_PS].
SAMPLE_GUARD_PS = 150
# clk_i cycles from the alignment edge to the first sample edge, past the period.
SAMPLE_LEAD_CLK = 4
# Hold of a stopped sample clock; a later restart ends it.
SCLK_STOP_PS = 10**12
# The preamble runs the sample clock at the window period for this many sample
# periods, plus PREAMBLE_CLK clk_i cycles.
PREAMBLE_PERIODS = 3
PREAMBLE_CLK = 8
DRAIN_CLK = 16

LAT_FACTOR = LATENCY_FACTOR
# Outer cap of the first observe wait of a kind, in clk_i per observe word: 32
# samples at a sample clock period of at most 128 clk_i. A cap only, never a
# contract; later waits use 16 x the clean time of the same seed.
OBS_WORD_CAP = 32 * 128

INTR_ENABLE_ALL = ENTROPY_SOURCE.mask("INTR_ENABLE")
NOISE_OVF = ENTROPY_SOURCE.fields("INTR_STATUS")["NOISE_OBS_OVERFLOW"]["bm"]
BIW_OVF = ENTROPY_SOURCE.fields("INTR_STATUS")["BIW_OBS_OVERFLOW"]["bm"]
ALL_LANES = (1 << NUM_LANES) - 1

FIFOS = {
    "noise": (ESRC_NOISE_OBS_STATUS, "NOISE_OBS_STATUS", ESRC_NOISE_OBS_RDATA, NOISE_OVF),
    "biw": (ESRC_BIW_OBS_STATUS, "BIW_OBS_STATUS", ESRC_BIW_OBS_RDATA, BIW_OVF),
}


def _get(value: int, reg: str, field: str) -> int:
    meta = ENTROPY_SOURCE.fields(reg)[field]
    return (value & meta["bm"]) >> meta["bp"]


def _val(reg: str, **fields: int) -> int:
    return ENTROPY_SOURCE.value(reg, **fields)


def _noise_ctrl(raw: int, lane_sel: int, flush: int = 0) -> int:
    return _val("NOISE_OBS_CTRL", RAW_ENABLE=raw, LANE_SEL=lane_sel, FLUSH=flush)


def _effective(lane_sel: int) -> int:
    return lane_sel if lane_sel < NUM_LANES else 0


def _word(z: int) -> int:
    return ALL_ONES if z else 0


@dataclass(frozen=True)
class Plan:
    seed: int
    order: tuple[int, ...]
    z_lane: tuple[int, ...]
    flush_lane: int
    flush_z: int
    f: int
    k: int
    z_lock: tuple[int, ...]
    balanced: tuple[Balanced, ...]
    seq_lane: int
    seq: tuple[int, ...]
    fast: tuple[int, ...]

    def describe(self) -> str:
        return (
            f"order={list(self.order)} z_lane={list(self.z_lane)} flush_lane={self.flush_lane} "
            f"flush_z={self.flush_z} f={self.f} k={self.k} z_lock={list(self.z_lock)} "
            f"{describe(self.balanced)} seq_lane={self.seq_lane} "
            f"seq={[f'0x{w:08x}' for w in _words(self.seq)]} "
            f"fast={[f'0x{w:08x}' for w in _words(self.fast)]}"
        )


def _words(bits) -> list[int]:
    """Full 32-bit words of ``bits``, LSB first."""
    return [
        sum(b << j for j, b in enumerate(bits[32 * w : 32 * w + 32]))
        for w in range(len(bits) // 32)
    ]


def _draw_seq(rng: SepSeededRng, words: int) -> tuple[int, ...]:
    """Seeded bits; bit SEQ_PAIR[1] of each word is the complement of bit SEQ_PAIR[0],
    and the last bit is the complement of the bit before it."""
    bits: list[int] = []
    for _ in range(words):
        word = [rng.getrandbits(1) for _ in range(32)]
        word[SEQ_PAIR[1]] = 1 - word[SEQ_PAIR[0]]
        bits += word
    bits[-1] = 1 - bits[-2]
    return tuple(bits)


def _indel_align(got: list[int], want: tuple[int, ...]) -> tuple[int, int]:
    """(lost, repeated) of the fewest deletions and insertions that align ``got`` with a
    prefix of ``want``."""
    inf = (len(got) + len(want) + 1, 0, 0)
    prev = [(j, j, 0) for j in range(len(want) + 1)]
    for i in range(1, len(got) + 1):
        cur = [inf] * (len(want) + 1)
        cur[0] = (i, 0, i)
        for j in range(1, len(want) + 1):
            c, lo, rp = prev[j]
            best = (c + 1, lo, rp + 1)
            c, lo, rp = cur[j - 1]
            best = min(best, (c + 1, lo + 1, rp))
            if got[i - 1] == want[j - 1]:
                best = min(best, prev[j - 1])
            cur[j] = best
        prev = cur
    _, lost, rep = min(prev)
    return lost, rep


def _lane_order(rng: SepSeededRng) -> list[int]:
    """All 16 values; the first value and the value before each of 0, 12-15 are in 1..11.

    The five values that select lane 0 go into five drawn gaps after the eleven
    lane values, so every write changes the effective lane.
    """
    lanes = list(LANE_SEL_LANES)
    rng.shuffle(lanes)
    same = list(LANE_SEL_SAME_AS_0)
    rng.shuffle(same)
    gaps = set(rng.sample(range(len(lanes)), len(same)))
    order: list[int] = []
    for i, v in enumerate(lanes):
        order.append(v)
        if i in gaps:
            order.append(same.pop())
    return order


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    order = _lane_order(rng)
    z_lane: list[int] = []
    for _ in range(DRAW_TRIES):
        z_lane = [rng.getrandbits(1) for _ in range(LANE_SEL_VALUES)]
        if 0 in z_lane and 1 in z_lane:
            break
    else:
        raise ValueError(f"seed {seed}: no z draw with both values in {DRAW_TRIES} tries")
    flush_lane = rng.randrange(NUM_LANES)
    flush_z = rng.getrandbits(1)
    f = rng.randrange(4, 9)
    k = rng.randrange(1, 5)
    z_lock = tuple(rng.getrandbits(1) for _ in range(4))
    balanced = tuple(balanced_lanes(rng))
    seq_lane = rng.randrange(NUM_LANES)
    seq = _draw_seq(rng, SEQ_WORDS)
    fast = tuple(rng.getrandbits(1) for _ in range(FAST_BITS))
    return Plan(
        seed,
        tuple(order),
        tuple(z_lane),
        flush_lane,
        flush_z,
        f,
        k,
        z_lock,
        balanced,
        seq_lane,
        seq,
        fast,
    )


class _EsrcRegs(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


@pyuvm.test()
class sep_esrc_observe_fifo_rand_test(sep_base_test):
    """Ungated capture, lane select, flush, overflow and lock of the observe FIFOs."""

    # CHK-OBS-PACK grades the first word after a packer restart against the
    # 32-sample rule of NOISE_OBS_RDATA; it is graded like every other check.
    required_evidence = (
        "CHK-OBS-UNGATED",
        "CHK-OBS-LANE",
        "CHK-OBS-PACK",
        "CHK-OBS-FLUSH",
        "CHK-OBS-OVERFLOW",
        "CHK-OBS-LOCK",
        "CHK-OBS-OFF",
        "CHK-OBS-SEQ",
        "CHK-SYNC-DEPTH",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=PARK)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.esrc = _EsrcRegs(self)
        self.p: int | None = None
        # Measured time of the first observe word of each FIFO (clk_i): BIW from the
        # clean ungated trial, noise from the failing ungated trial.
        self.t_biw_word: int | None = None
        self.t_noise_word: int | None = None
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        self._release_stuck()
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        self.noise.start(plan.balanced)
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)

        t_clean = await self._ungated_clean()
        await self._ungated_failing(t_clean)
        await self._lane_leg()
        await self._flush_leg()
        await self._overflow_leg()
        await self._main_chain_leg()
        await self._off_leg()
        for i, fifo in enumerate(("noise", "biw")):
            t_cap = await self._lock1(fifo, plan.z_lock[2 * i])
            await self._lock0(fifo, plan.z_lock[2 * i + 1], t_cap)
        await self._seq_leg()
        close_graded_window(self.logger)
        self._release_stuck()
        await self.noise.stop()
        self.chk.finish()

    # --- bus, clocks and bounds -----------------------------------------------
    async def _wr(self, addr: int, data: int) -> None:
        await self.esrc._wr(addr, data)

    async def _rd(self, addr: int) -> int:
        return await self.esrc._rd(addr)

    def _now(self) -> int:
        return self.noise.clk

    def _period(self) -> int:
        return self.setup.period()

    def _bound(self, kind: str, cap: int) -> int:
        return self.setup.bound(kind, cap)

    def _learn(self, kind: str, clocks: int) -> None:
        self.setup.learn(kind, clocks)

    async def _poll(self, addr: int, getter, pred, bound: int):
        """Reads until pred(getter(value)) holds or bound clocks pass: (ok, field, clocks)."""
        t0 = self._now()
        field = 0
        for _ in range(bound + 1):
            field = getter(await self._rd(addr))
            if pred(field):
                return True, field, self._now() - t0
            if self._now() - t0 > bound:
                break
        return False, field, self._now() - t0

    async def _level(self, fifo: str) -> int:
        addr, reg, _, _ = FIFOS[fifo]
        return _get(await self._rd(addr), reg, "LEVEL")

    async def _poll_level(self, fifo: str, pred, bound: int):
        addr, reg, _, _ = FIFOS[fifo]
        return await self._poll(addr, lambda v: _get(v, reg, "LEVEL"), pred, bound)

    async def _pop(self, fifo: str) -> int:
        return await self._rd(FIFOS[fifo][2])

    async def _pop_to_empty(self, fifo: str) -> int:
        """Pop until LEVEL reads 0 with capture off; more than the FIFO depth fails the leaf."""
        pops = 0
        while True:
            level = await self._level(fifo)
            if level == 0:
                return pops
            for _ in range(level):
                await self._pop(fifo)
                pops += 1
            if pops > FIFO_DEPTH_MAX:
                raise AssertionError(f"{fifo} observe FIFO not empty after {pops} pops")

    def _release_stuck(self) -> None:
        dut = cocotb.top
        dut.esrc_noise_stuck_en_i.value = 0
        dut.esrc_noise_stuck_val_i.value = 0

    def _drive(self, lane: int, z: int) -> None:
        """Lane ``lane`` carries z and every other lane the opposite value."""
        bits = [z if j == lane else 1 - z for j in range(NUM_LANES)]
        dut = cocotb.top
        dut.esrc_noise_stuck_val_i.value = sum(b << j for j, b in enumerate(bits))
        dut.esrc_noise_stuck_en_i.value = ALL_LANES
        self.noise.set_lanes([Stuck(b) for b in bits])
        self.logger.info("LANE-DRIVE lane=%d z=%d others=%d", lane, z, 1 - z)

    # --- set-up -----------------------------------------------------------------
    async def _trng_reset(self) -> int:
        return await self.setup.trng_reset(
            balanced=self.plan.balanced, before_release=self._release_stuck
        )

    async def _setup(self, *, clean: bool = True, extra_writes=()) -> None:
        close_graded_window(self.logger)
        mark = await self._trng_reset()
        # entropy_source.adoc RING_OSC_CTRL: a clear bit selects the external sample
        # clock; the source of a lane changes only while its generator is disabled.
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE", ENABLE=0))
        await self._wr(ESRC_RING_OSC_CTRL, _val("RING_OSC_CTRL", SAMPLE_CLK_SELECT=0))
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))
        await self._wr(ESRC_INTR_ENABLE, INTR_ENABLE_ALL)
        await self._wr(ESRC_ALERT_THRESHOLD, _val("ALERT_THRESHOLD", THRESHOLD=0))
        if not clean:
            return
        await SepEsrcCleanStart(
            self, self.noise, self.plan.balanced, window=WINDOW, extra_writes=extra_writes
        ).run(release_mark=mark)
        self.p = await self.setup.measure_period(self.chk)
        await self.setup.wait_boot_done(self.esrc, WINDOW)

    # --- ungated leg (steps 2-4) ------------------------------------------------------
    async def _ungated_clean(self) -> int:
        extra = (
            (ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, 0)),
            (ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=1)),
        )
        await self._setup(extra_writes=extra)
        cap = WINDOW * self._period()
        ok, _, t_clean = await self._poll_level("biw", lambda v: v > 0, cap)
        # The wait of the failing trial is at least one strobe period.
        t_wait = max(t_clean, self._period())
        self.t_biw_word = t_wait if ok else None
        self.chk.ctrl("OBS-UNGATED-CLEAN", ok, t_clean_clk=t_clean, t_used_clk=t_wait, bound=cap)
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, 0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))
        return t_wait

    async def _ungated_failing(self, t_clean: int) -> None:
        await self._setup(clean=False)
        await self._wr(ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL))
        self.noise.set_lanes([Stuck(0)] * NUM_LANES)
        await self.noise.wait_words(2, 4 * self._period() * 4)
        bc0, bm0 = self.noise.byte_control()
        self.noise.byte_check(True)
        open_graded_window(TEST, self.logger)
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, 0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=1))
        bound = self._bound("noise_first", 2 * OBS_WORD_CAP * 20)
        ok, _, clocks = await self._poll_level("noise", lambda v: v > 0, bound)
        self.t_noise_word = clocks if ok else None
        if ok:
            self._learn("noise_first", clocks)
        wait = UNGATED_WAIT_FACTOR * t_clean
        await ClockCycles(cocotb.top.clk_i, wait)
        done = _get(await self._rd(ESRC_MAIN_SM_STATUS), "MAIN_SM_STATUS", "BOOT_PHASE_DONE")
        noise_level = await self._level("noise")
        biw_level = await self._level("biw")
        close_graded_window(self.logger)
        self.noise.byte_check(False)
        bc1, bm1 = self.noise.byte_control()
        compared, mism = bc1 - bc0, bm1 - bm0
        self.chk.ctrl("NOISE-BYTES", mism == 0 and compared > 0, compared=compared, mismatched=mism)
        self.chk.ctrl("OBS-UNGATED", biw_level == 0, ctrl_biw_obs_level=biw_level)
        fields = {
            "boot_done": done,
            "noise_obs_level": noise_level,
            "ctrl_biw_obs_level": biw_level,
            "t_clean_clk": t_clean,
            "wait_clk": wait,
        }
        if not ok:
            fields["reason"] = f"timeout:noise_obs_level bound={bound}"
        self.chk.ok("OBS-UNGATED", ok and done == 0 and noise_level > 0, **fields)
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, 0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))

    # --- lane leg (steps 5-10) ----------------------------------------------------------
    async def _lane_leg(self) -> None:
        plan = self.plan
        await self._setup()
        open_graded_window(TEST, self.logger)
        cur = 0
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, cur))
        for v, z in zip(plan.order, plan.z_lane):
            await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, cur))
            await self._pop_to_empty("noise")
            self._drive(_effective(v), z)
            await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, cur))
            b4 = self._bound("obs_4", WORDS_BEFORE_CHANGE * OBS_WORD_CAP * 20)
            ok4, _, c4 = await self._poll_level("noise", lambda x: x >= WORDS_BEFORE_CHANGE, b4)
            if ok4:
                self._learn("obs_4", c4)
            before = await self._level("noise")
            await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, v))
            after = await self._level("noise")
            b8 = self._bound("obs_8", WORDS_AFTER_CHANGE * OBS_WORD_CAP * 20)
            ok8, _, c8 = await self._poll_level("noise", lambda x: x >= WORDS_AFTER_CHANGE, b8)
            if ok8:
                self._learn("obs_8", c8)
            words = [await self._pop("noise") for _ in range(WORDS_AFTER_CHANGE)] if ok8 else []
            self._grade_lane(v, cur, z, ok4, ok8, before, after, words, b4, b8)
            cur = v
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, cur))
        close_graded_window(self.logger)

    def _grade_lane(self, v, cur, z, ok4, ok8, before, after, words, b4, b8) -> None:
        expect = _word(z)
        old = _word(1 - z)
        lane = _effective(v)
        reason = "" if ok4 else f"timeout:level_before bound={b4}"
        reason = reason or ("" if ok8 else f"timeout:level_after bound={b8}")
        self.chk.ctrl(
            "OBS-LANE",
            ok4 and before >= WORDS_BEFORE_CHANGE and _effective(cur) != lane,
            lane_sel=v,
            level_before=before,
            prev_lane=_effective(cur),
        )
        rest = words[1:]
        mism = sum(1 for w in rest if w != expect)
        fields = {
            "lane_sel": v,
            "lane": lane,
            "z": z,
            "words": len(rest),
            "expect": f"0x{expect:08x}",
            "mismatches": mism,
            "level_before": before,
            "level_after_change": after,
            "popped": [f"0x{w:08x}" for w in words],
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "OBS-LANE",
            not reason and len(rest) == WORDS_AFTER_CHANGE - 1 and mism == 0 and after < before,
            **fields,
        )
        first = words[0] if words else None
        pack = {
            "lane_sel": v,
            "lane": lane,
            "z": z,
            "first": "none" if first is None else f"0x{first:08x}",
            "expect": f"0x{expect:08x}",
        }
        if reason:
            pack["reason"] = reason
        self.chk.ok("OBS-PACK", first == expect, **pack)
        olds = sum(1 for w in words if w == old)
        self.chk.ok(
            "OBS-FLUSH",
            not reason and olds == 0 and after < before,
            via="lane",
            lane_sel=v,
            old_words_after=olds,
            words=len(words),
            old=f"0x{old:08x}",
        )

    # --- flush leg (steps 11-13) ---------------------------------------------------------
    async def _flush_leg(self) -> None:
        plan = self.plan
        a, z = plan.flush_lane, plan.flush_z
        await self._setup()
        open_graded_window(TEST, self.logger)
        self._drive(a, z)
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, a))
        bound = self._bound("obs_8", WORDS_AFTER_CHANGE * OBS_WORD_CAP * 20)
        ok_f, _, _ = await self._poll_level("noise", lambda x: x >= plan.f, bound)
        self._drive(a, 1 - z)
        lc = await self._level("noise")
        ok_n, _, _ = await self._poll_level("noise", lambda x: x >= lc + FLUSH_NEW_WORDS, bound)
        before = await self._level("noise")
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, a, flush=1))
        after = await self._level("noise")
        ok_m, m, _ = await self._poll_level("noise", lambda x: x >= FLUSH_NEW_WORDS, bound)
        words = [await self._pop("noise") for _ in range(m)] if ok_m else []
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, a))
        close_graded_window(self.logger)
        new, old = _word(1 - z), _word(z)
        olds = sum(1 for w in words if w == old)
        others = sum(1 for w in words if w != new)
        self.chk.ctrl("OBS-FLUSH", ok_f and ok_n and new != old, level_at_change=lc, f=plan.f)
        fields = {
            "via": "flush",
            "lane": a,
            "level_before": before,
            "level_after": after,
            "old_words_after": olds,
            "not_new_words": others,
            "words": len(words),
        }
        if not (ok_f and ok_n and ok_m):
            fields["reason"] = f"timeout:level bound={bound}"
        self.chk.ok(
            "OBS-FLUSH",
            ok_f and ok_n and ok_m and after < before and olds == 0 and others == 0 and words,
            **fields,
        )

    # --- overflow leg (steps 14-16) ------------------------------------------------------
    async def _overflow_leg(self) -> None:
        await self._setup()
        # A constant lane 0 gives the noise observe words a known source; the
        # values are not graded.
        self._drive(0, 0)
        intr0 = await self._rd(ESRC_INTR_STATUS)
        pre = {f: int(bool(intr0 & FIFOS[f][3])) for f in FIFOS}
        open_graded_window(TEST, self.logger)
        t0 = self._now()
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, 0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=1))
        depth: dict[str, int] = {}
        fill: dict[str, int] = {}
        seen: dict[str, bool] = {}
        for fifo in ("noise", "biw"):
            bit = FIFOS[fifo][3]
            cap = FIFO_DEPTH_MAX * OBS_WORD_CAP * 2
            ok, _, _ = await self._poll(ESRC_INTR_STATUS, lambda v, b=bit: v & b, bool, cap)
            seen[fifo] = ok
            fill[fifo] = self._now() - t0
            depth[fifo] = await self._level(fifo)
        wait = 2 * max(fill.values())
        await ClockCycles(cocotb.top.clk_i, wait)
        later = {fifo: await self._level(fifo) for fifo in FIFOS}
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, 0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))
        w1c: dict[str, int] = {}
        held: dict[str, int] = {}
        for fifo in ("noise", "biw"):
            bit = FIFOS[fifo][3]
            await self._pop_to_empty(fifo)
            # The overflow bit is RW1C (entropy_source.adoc:134, :136): it still reads 1
            # after the drain, so the clear below is caused by the write-one.
            held[fifo] = int(bool(await self._rd(ESRC_INTR_STATUS) & bit))
            await self._wr(ESRC_INTR_STATUS, bit)
            w1c[fifo] = int(bool(await self._rd(ESRC_INTR_STATUS) & bit))
        close_graded_window(self.logger)
        for fifo in ("noise", "biw"):
            self.chk.ctrl("OBS-OVERFLOW", pre[fifo] == 0, fifo=fifo, overflow_before=pre[fifo])
            self.chk.ctrl(
                "OBS-OVERFLOW", held[fifo] == 1, fifo=fifo, overflow_before_w1c=held[fifo]
            )
            fields = {
                "fifo": fifo,
                "depth": depth[fifo],
                "overflow": int(seen[fifo]),
                "level_after_two_fills": later[fifo],
                "w1c": w1c[fifo],
                "fill_clk": fill[fifo],
                "wait_clk": wait,
            }
            if not seen[fifo]:
                fields["reason"] = "timeout:overflow"
            self.chk.ok(
                "OBS-OVERFLOW",
                seen[fifo] and depth[fifo] > 0 and later[fifo] == depth[fifo] and w1c[fifo] == 0,
                **fields,
            )

    # --- main-chain leg (logged only) ----------------------------------------------------
    async def _main_chain_leg(self) -> None:
        await self._setup()
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        cap = MAIN_WORDS * 64 * self._period()
        w_clk = await self._clocks_for_words(MAIN_WORDS, cap)
        off = await self._words_in(w_clk) if w_clk else 0
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, 0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=1))
        on = await self._words_in(w_clk) if w_clk else 0
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, 0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))
        self.chk.blocked("OBS-MAIN", "observe_capture_vs_main_chain_unstated")
        self.chk.obs("OBS-MAIN", words_obs_on=on, words_obs_off=off, window_clk=w_clk or "none")

    # --- capture-off leg ---------------------------------------------------------------
    async def _off_leg(self) -> None:
        """CHK-OBS-OFF: with both RAW_ENABLE fields 0 and the module running after the boot
        phase, neither observe FIFO takes a word over the hold: OFF_STROBES strobes and at
        least OFF_WORD_FACTOR x the measured first-word time of each FIFO, so the hold
        spans several observe words of each FIFO."""
        await self._setup()
        raw = {fifo: await self._read_raw(fifo) for fifo in FIFOS}
        before = {fifo: await self._level(fifo) for fifo in FIFOS}
        self.chk.ctrl(
            "OBS-OFF",
            all(v == 0 for v in raw.values()) and all(v == 0 for v in before.values()),
            noise_raw=raw["noise"],
            biw_raw=raw["biw"],
            noise_level_before=before["noise"],
            biw_level_before=before["biw"],
        )
        words = {"noise": self.t_noise_word, "biw": self.t_biw_word}
        hold = max([OFF_WORD_FACTOR * t for t in words.values() if t] + [0])
        open_graded_window(TEST, self.logger)
        t0 = self._now()
        bound = 2 * (OFF_STROBES + 1) * self._period()
        reason = ""
        if None in words.values():
            reason = "no_word_time"
        try:
            await self.noise.wait_words(OFF_STROBES, bound)
        except EsrcStrobeTimeout:
            reason = f"timeout:strobes bound={bound}"
        rest = hold - (self._now() - t0)
        if rest > 0:
            await ClockCycles(cocotb.top.clk_i, rest)
        held = self._now() - t0
        after = {fifo: await self._level(fifo) for fifo in FIFOS}
        close_graded_window(self.logger)
        fields = {
            "noise_level": after["noise"],
            "biw_level": after["biw"],
            "strobes": OFF_STROBES,
            "hold_clk": held,
            "expect_hold_clk_min": hold,
            "t_noise_word_clk": words["noise"] if words["noise"] else "none",
            "t_biw_word_clk": words["biw"] if words["biw"] else "none",
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "OBS-OFF",
            not reason and held >= hold and after["noise"] == 0 and after["biw"] == 0,
            **fields,
        )

    async def _clocks_for_words(self, words: int, cap: int) -> int | None:
        dut = cocotb.top
        seen = 0
        for clk in range(1, cap + 1):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            seen += self.rd(dut.esrc_compress_vld_o)
            if seen >= words:
                await NextTimeStep()
                return clk
        await NextTimeStep()
        return None

    async def _words_in(self, clocks: int) -> int:
        dut = cocotb.top
        seen = 0
        for _ in range(clocks):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            seen += self.rd(dut.esrc_compress_vld_o)
        await NextTimeStep()
        return seen

    # --- lock leg (steps 19-23) ------------------------------------------------------------
    async def _write_raw(self, fifo: str, raw: int) -> None:
        if fifo == "noise":
            await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(raw, 0))
        else:
            await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=raw))

    async def _read_raw(self, fifo: str) -> int:
        if fifo == "noise":
            return _get(await self._rd(ESRC_NOISE_OBS_CTRL), "NOISE_OBS_CTRL", "RAW_ENABLE")
        return _get(await self._rd(ESRC_BIW_OBS_CTRL), "BIW_OBS_CTRL", "RAW_ENABLE")

    async def _lock(self) -> int:
        await self._wr(ESRC_FIPS_LOCK, _val("FIPS_LOCK", LOCK=1))
        return _get(await self._rd(ESRC_FIPS_LOCK), "FIPS_LOCK", "LOCK")

    async def _lock1(self, fifo: str, z: int) -> int | None:
        """Locked at 1; returns t_cap (None if capture never reached 2 words)."""
        plan = self.plan
        await self._setup()
        self._drive(0, z)
        open_graded_window(TEST, self.logger)
        t0 = self._now()
        await self._write_raw(fifo, 1)
        raw_rb = await self._read_raw(fifo)
        cap = self._bound(f"cap_{fifo}", 2 * OBS_WORD_CAP * 20)
        ok2, _, t_cap = await self._poll_level(fifo, lambda x: x >= 2, cap)
        t_cap = self._now() - t0 if ok2 else None
        okk, _, _ = await self._poll_level(fifo, lambda x: x >= plan.k, cap)
        lock = await self._lock()
        level_at_lock = await self._level(fifo)
        self.chk.ctrl(
            "OBS-LOCK",
            raw_rb == 1 and lock == 1 and ok2,
            fifo=fifo,
            raw_readback=raw_rb,
            lock=lock,
        )
        words: list[int] = []
        pop_ok = ok2 and okk
        pop_bound = LAT_FACTOR * t_cap if t_cap else cap
        if pop_ok:
            for _ in range(level_at_lock + LOCK_EXTRA_POPS):
                ok, _, _ = await self._poll_level(fifo, lambda x: x > 0, pop_bound)
                if not ok:
                    pop_ok = False
                    break
                words.append(await self._pop(fifo))
        flush_after: int | str = "n/a"
        flush_fields: dict = {}
        value_ok = True
        flush_ok = True
        if fifo == "noise":
            last = words[-LOCK_EXTRA_POPS:]
            value_ok = len(last) == LOCK_EXTRA_POPS and all(w == _word(z) for w in last)
            # FLUSH under the lock (entropy_source.adoc:827: it discards the buffered
            # words). LOCK_FLUSH_WORDS words of z are buffered, then the lane changes to
            # 1 - z and FLUSH_NEW_WORDS more words are captured, so the FIFO holds old
            # words of z and words of the new value at the FLUSH. Every word popped after
            # the FLUSH completed after it, so it holds new samples only (the lane leg
            # grades the same: words 2 on of a change hold the new value); a word of z or
            # a mixed word popped after the FLUSH is a word the FLUSH kept.
            okz, _, _ = await self._poll_level(fifo, lambda x: x >= LOCK_FLUSH_WORDS, pop_bound)
            self._drive(0, 1 - z)
            lc = await self._level(fifo)
            okc, _, _ = await self._poll_level(fifo, lambda x: x >= lc + FLUSH_NEW_WORDS, pop_bound)
            okf = okz and okc
            before = await self._level(fifo)
            await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, 0, flush=1))
            flush_after = await self._level(fifo)
            okn, m, _ = await self._poll_level(fifo, lambda x: x >= FLUSH_NEW_WORDS, pop_bound)
            post = [await self._pop(fifo) for _ in range(m)] if okn else []
            new, old = _word(1 - z), _word(z)
            olds = sum(1 for w in post if w == old)
            not_new = sum(1 for w in post if w != new)
            flush_ok = (
                okf and okn and flush_after < before and bool(post) and olds == 0 and not_new == 0
            )
            flush_fields = {
                "noise_flush_level_before": before,
                "flush_old_words_after": olds,
                "flush_not_new_words": not_new,
                "flush_words": len(post),
                "flush_expect": f"0x{new:08x}",
            }
            if not (okf and okn):
                flush_fields["flush_reason"] = f"timeout:level bound={pop_bound}"
        close_graded_window(self.logger)
        fields = {
            "fifo": fifo,
            "locked_at": 1,
            "level_at_lock": level_at_lock,
            "post_lock_pops": len(words),
            "expect_pops": level_at_lock + LOCK_EXTRA_POPS,
            "noise_flush_level_after": flush_after,
            **flush_fields,
            "capture_clk": t_cap if t_cap is not None else "none",
            "wait_clk": pop_bound,
        }
        if fifo == "noise":
            fields["last_words"] = [f"0x{w:08x}" for w in words[-LOCK_EXTRA_POPS:]]
            fields["expect"] = f"0x{_word(z):08x}"
        if not pop_ok:
            fields["reason"] = f"timeout:level bound={pop_bound}"
        self.chk.ok(
            "OBS-LOCK",
            pop_ok and len(words) == level_at_lock + LOCK_EXTRA_POPS and value_ok and flush_ok,
            **fields,
        )
        if t_cap is not None:
            self._learn(f"cap_{fifo}", t_cap)
        return t_cap

    async def _lock0(self, fifo: str, z: int, t_cap: int | None) -> None:
        await self._setup()
        self._drive(0, z)
        raw0 = await self._read_raw(fifo)
        open_graded_window(TEST, self.logger)
        lock = await self._lock()
        await self._write_raw(fifo, 1)
        raw_rb = await self._read_raw(fifo)
        wait = LOCK0_WAIT_FACTOR * t_cap if t_cap else 0
        if wait:
            await ClockCycles(cocotb.top.clk_i, wait)
        level = await self._level(fifo)
        # Keep the window open two clocks past the STATUS read so the FCOV sampler sees it.
        await ClockCycles(cocotb.top.clk_i, 2)
        close_graded_window(self.logger)
        self.chk.ctrl(
            "OBS-LOCK",
            t_cap is not None and raw0 == 0 and lock == 1 and raw_rb == 0,
            fifo=fifo,
            locked_at=0,
            ctrl_locked1_capture_clk=t_cap if t_cap is not None else "none",
            raw_before=raw0,
            lock=lock,
            post_lock_write_readback=raw_rb,
        )
        self.chk.ok(
            "OBS-LOCK",
            t_cap is not None and level == 0,
            fifo=fifo,
            locked_at=0,
            level=level,
            capture_clk=t_cap if t_cap is not None else "none",
            wait_clk=wait,
        )

    # --- sample-clock sequence leg ---------------------------------------------------------
    def _clk_ps(self) -> int:
        t = round(self.cfg.sys_clk_period_ns * 1000)
        if t % 2:
            raise ValueError(f"clk_i period {t} ps is odd: no whole-ps falling edge")
        return t

    async def _seq_leg(self) -> None:
        """CHK-OBS-SEQ and CHK-SYNC-DEPTH at a sample period of 8 x clk_i + 2 ps, then
        OBS-OBS-FAST at 2 x clk_i + 2 ps."""
        plan = self.plan
        lane = plan.seq_lane
        t = self._clk_ps()
        last = SAMPLE_GUARD_PS + SAMPLE_DRIFT_PS * (SEQ_BITS - 1)
        if last > t // 2 - SAMPLE_GUARD_PS:
            raise ValueError(f"sample edge offset {last} ps leaves the guard of a {t} ps clk_i")
        await self._setup(clean=False)
        reg = f"GENERATOR_{lane}_SAMPLE_CLK_CONFIG"
        addr = sym(f"ENTROPY_SOURCE_{reg}_REG_ADDR")
        # entropy_source.adoc GENERATOR_<n>_SAMPLE_CLK_CONFIG: the divide of a lane
        # changes only while its generator is disabled.
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE", ENABLE=0))
        await self._wr(addr, _val(reg, SAMPLE_CLK_DIVIDE=0))
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))
        div = _get(await self._rd(addr), reg, "SAMPLE_CLK_DIVIDE")
        sel = _get(await self._rd(ESRC_RING_OSC_CTRL), "RING_OSC_CTRL", "SAMPLE_CLK_SELECT")
        self.chk.ctrl(
            "OBS-SEQ",
            div == 0 and not (sel >> lane) & 1,
            lane=lane,
            sample_clk_divide=div,
            sample_clk_select=f"0x{sel:03x}",
        )
        open_graded_window(TEST, self.logger)
        slow = await self._seq_window(lane, plan.seq, SEQ_PERIOD_CLK, depth=True)
        self._grade_seq(lane, plan.seq, slow)
        fast = await self._seq_window(lane, plan.fast, FAST_PERIOD_CLK, depth=False)
        close_graded_window(self.logger)
        self.restart_clock(SCLK, self.cfg.entropy_clk_period_ns)
        self._release_stuck()
        got = [(w >> j) & 1 for w in fast["words"] for j in range(32)]
        lost, rep = _indel_align(got, plan.fast)
        self.chk.obs(
            "OBS-FAST",
            lane=lane,
            period_ps=fast["period_ps"],
            edges=fast["edges"],
            expect_edges=len(plan.fast),
            level=fast["level"],
            bits_captured=len(got),
            lost=lost,
            repeated=rep,
            words=[f"0x{w:08x}" for w in fast["words"]],
            expect=[f"0x{w:08x}" for w in _words(plan.fast)],
            **fast["pre"],
        )

    async def _seq_window(self, lane: int, bits, period_clk: int, *, depth: bool) -> dict:
        """Drive ``bits`` on ``lane``, one bit per sample edge, from a stopped sample clock;
        returns the edges driven, the edge times, the depth samples and the popped words."""
        dut = cocotb.top
        t = self._clk_ps()
        period = period_clk * t + SAMPLE_DRIFT_PS
        period_ns = period / 1000
        n = len(bits)
        window = "sync" if depth else "fast"
        # Preamble: the lane carries the complement of bit 0 on the running clock, so
        # sample edge 0 changes the synchronized bit.
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, lane))
        await self._pop_to_empty("noise")
        dut.esrc_noise_stuck_val_i.value = (1 - bits[0]) << lane
        dut.esrc_noise_stuck_en_i.value = 1 << lane
        self.restart_clock(SCLK, period_ns)
        await ClockCycles(dut.clk_i, PREAMBLE_PERIODS * (period_clk + 1) + PREAMBLE_CLK)
        self.restart_clock(SCLK, period_ns, SCLK_STOP_PS)
        await ClockCycles(dut.clk_i, DRAIN_CLK)
        pre_bit = (self.rd(dut.esrc_noise_bit_o, mask=1 << lane) >> lane) & 1
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(1, lane))
        raw = await self._read_raw("noise")
        level0 = await self._level("noise")
        pre = {
            "raw_enable": raw,
            "level_before": level0,
            "preamble_bit": pre_bit,
            "expect_preamble_bit": 1 - bits[0],
        }
        if depth:
            self.chk.ctrl(
                "OBS-SEQ",
                raw == 1 and level0 == 0 and pre_bit == 1 - bits[0],
                window=window,
                lane=lane,
                period_ps=period,
                **pre,
            )
        dut.esrc_noise_stuck_val_i.value = bits[0] << lane
        times: list[int] = []
        clk_times: list[int] = []
        samples: list[tuple[int, int, int]] = []
        done = Event()
        watched = Event()

        async def drive() -> None:
            for k in range(n):
                await RisingEdge(dut.entropy_rosc_sample_clk_i)
                times.append(get_sim_time("ps"))
                if k + 1 < n:
                    dut.esrc_noise_stuck_val_i.value = bits[k + 1] << lane
            self.restart_clock(SCLK, period_ns, SCLK_STOP_PS)
            done.set()

        async def watch(bound: int) -> None:
            # Sample edge k is seen as a 0 -> 1 change of the pin between two clk_i
            # rising edges; the bit is read at the 1st and the 2nd of them.
            prev = self.rd(dut.entropy_rosc_sample_clk_i)
            open_k: int | None = None
            first = 0
            k = 0
            for _ in range(bound):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                clk_times.append(get_sim_time("ps"))
                lvl = self.rd(dut.entropy_rosc_sample_clk_i)
                bit = (self.rd(dut.esrc_noise_bit_o, mask=1 << lane) >> lane) & 1
                if open_k is not None:
                    samples.append((open_k, first, bit))
                    open_k = None
                if prev == 0 and lvl == 1:
                    open_k, first = k, bit
                    k += 1
                prev = lvl
                if k >= n and open_k is None:
                    break
            await NextTimeStep()
            watched.set()

        await RisingEdge(dut.clk_i)
        t_ref = get_sim_time("ps")
        high = self.rd(dut.entropy_rosc_sample_clk_i)
        # A clock restarts high: from a high pin its first rising edge is one period later.
        lead = (period_clk + SAMPLE_LEAD_CLK) * t + SAMPLE_GUARD_PS
        phase = lead - period if high else lead
        bound = (n + 2) * (period_clk + 1) + period_clk + 2 * SAMPLE_LEAD_CLK
        watcher = cocotb.start_soon(watch(bound)) if depth else None
        self.restart_clock(SCLK, period_ns, phase)
        driver = cocotb.start_soon(drive())
        await First(done.wait(), ClockCycles(dut.clk_i, bound))
        if not done.is_set():
            driver.cancel()
            self.restart_clock(SCLK, period_ns, SCLK_STOP_PS)
        if watcher is not None:
            await First(watched.wait(), ClockCycles(dut.clk_i, bound))
        await ClockCycles(dut.clk_i, DRAIN_CLK)
        await self._wr(ESRC_NOISE_OBS_CTRL, _noise_ctrl(0, lane))
        level = await self._level("noise")
        words = [await self._pop("noise") for _ in range(min(level, FIFO_DEPTH_MAX))]
        self.logger.info(
            "SEQ-WINDOW window=%s lane=%d period_ps=%d t_ref=%d phase_ps=%d edges=%d level=%d",
            window,
            lane,
            period,
            t_ref,
            phase,
            len(times),
            level,
        )
        return {
            "period_ps": period,
            "edges": len(times),
            "times": times,
            "clk_times": clk_times,
            "samples": samples,
            "level": level,
            "words": words,
            "pre": pre,
        }

    def _edge_distance(self, times: list[int], clk_times: list[int]) -> int | None:
        """Smallest distance (ps) of a sample edge from a clk_i rising or falling edge."""
        t = self._clk_ps()
        best: int | None = None
        for ts in times:
            i = bisect_right(clk_times, ts) - 1
            if i < 0:
                return None
            ph = ts - clk_times[i]
            d = min(ph, abs(ph - t // 2), t - ph)
            best = d if best is None else min(best, d)
        return best

    def _grade_seq(self, lane: int, bits, res: dict) -> None:
        n = len(bits)
        timeout = res["edges"] != n
        expect = _words(bits)
        words = res["words"]
        bad = [
            w
            for w in range(max(len(words), len(expect)))
            if w >= len(words) or w >= len(expect) or words[w] != expect[w]
        ]
        fields = {
            "lane": lane,
            "period_ps": res["period_ps"],
            "edges": res["edges"],
            "level": res["level"],
            "expect_level": SEQ_WORDS,
            "pair": list(SEQ_PAIR),
            "bad_words": bad,
            "words": [f"0x{w:08x}" for w in words],
            "expect": [f"0x{w:08x}" for w in expect],
        }
        if timeout:
            fields["reason"] = f"timeout:sample_edges driven={res['edges']}"
        self.chk.ok(
            "OBS-SEQ",
            not timeout and res["level"] == SEQ_WORDS and not bad,
            **fields,
        )
        dist = self._edge_distance(res["times"], res["clk_times"])
        self.chk.ctrl(
            "SYNC-DEPTH",
            dist is not None and dist >= SAMPLE_GUARD_PS and not timeout,
            lane=lane,
            edges=res["edges"],
            min_edge_distance_ps=dist if dist is not None else "none",
            guard_ps=SAMPLE_GUARD_PS,
            drift_ps=SAMPLE_DRIFT_PS,
        )
        early = []
        late = []
        transitions = 0
        for k, first, second in res["samples"]:
            prev = bits[k - 1] if k else 1 - bits[0]
            if bits[k] != prev:
                transitions += 1
                if first != prev:
                    early.append(k)
            if second != bits[k]:
                late.append(k)
        expect_tr = sum(1 for k in range(n) if bits[k] != (bits[k - 1] if k else 1 - bits[0]))
        fields = {
            "lane": lane,
            "sample_edges": len(res["samples"]),
            "expect_edges": n,
            "transitions": transitions,
            "expect_transitions": expect_tr,
            "changed_at_edge1": len(early),
            "wrong_at_edge2": len(late),
            "first_early": early[0] if early else "none",
            "first_late": late[0] if late else "none",
        }
        if timeout:
            fields["reason"] = f"timeout:sample_edges driven={res['edges']}"
        self.chk.ok(
            "SYNC-DEPTH",
            not timeout
            and len(res["samples"]) == n
            and transitions == expect_tr
            and transitions > 0
            and not early
            and not late,
            **fields,
        )
