# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The effect of the ESRC conditioning options on the data path.

Contract (``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc``, ``CTRL``,
``SHA256_STATUS``, ``DECORRELATOR_CTRL``, ``DECORRELATOR_MASK``;
``hw/ip/entropy_source/doc/architecture.adoc``, Entropy Source, Decorrelation and
BIW Mixing, SHA-256 Whitening):
  * ``DECORRELATOR_MASK`` ANDs every decorrelated byte. With
    ``DECORRELATOR_CTRL.BYPASS`` set on a lane, a constant noise bit gives a
    constant byte (architecture.adoc:107; entropy_source.adoc:388, :398).
  * With ``CTRL.BYPASS_ENTROPY_COMPRESSOR`` set, the twelve bytes reach the FIFO
    as three 32-bit words in word order 0, 1, 2; generator 4n+k is in bits
    [8k+7:8k] of word n (architecture.adoc:118; entropy_source.adoc:108).
  * ``DOWNSAMPLE_RATE`` = N selects every (N+1)th decorrelator output while the
    compressor is bypassed (entropy_source.adoc:106).
  * ``DECORRELATOR_CTRL.SAMPLE_CLK_DIV`` = D sets the byte period to D + 1 cycles
    (entropy_source.adoc:387; architecture.adoc:107). While a lane is disabled
    its divider holds at zero, so a D written before the enable sets the distance
    to the first sample (architecture.adoc:113). The enable of a lane is
    ``RING_OSC_ENABLE.ENABLE`` (entropy_source.adoc:357).
  * With ``SHA256_WHITENING_ENABLE`` = 1, 16 input words give 8 digest words
    (architecture.adoc:142) and ``SHA256_STATUS.OUTPUT_COUNT`` reports 8 and
    counts down to 0; it stays 0 while bypassed (entropy_source.adoc:206). With
    it clear the BIW words reach the FIFO unchanged (architecture.adoc:142;
    entropy_source.adoc:104).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20: the TRNG is released, the
Key Manager and every engine are held. The exact-pattern noise driver
(``env/sep_esrc_pattern_noise.py``) drives ``balanced`` on all lanes from before
the first TRNG reset release and never stops; each leg changes the patterns.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the leg order, the partial mask M, the rate N_r (2 to 15), the lane
noise Z (12 bits with a 0 and a 1) and its polarity, the balanced lanes, the
divider value D_r (above the reset value, at most 1023) and the order of 0 and
D_r in the period walk.

Checkers:
  CHK-COND-MASK        each lane byte == (0xFF if Z[j] else 0x00) AND mask, 16 strobes,
                       for the mask 0xFF and for M (``esrc_decor_bytes_o``).
  CHK-COND-BYPASS      21 three-word outputs bit-exact against the packing rule for four
                       lane-signature passes and all-ones, whitening control 1 and 0.
  CHK-COND-DOWNSAMPLE  for N = 0, 1, N_r, 1023, exact: the span from the last word of
                       the second output after the rate write to the last word of the
                       sixth holds 12 words and (N+1) x 4 strobes of
                       ``esrc_decor_valid_o`` (entropy_source.adoc:106). The span is
                       aligned: every output in it is three words with no strobe
                       between them, the strobe gap is one value P, and both ends lie
                       the same number of clocks after their last strobe, so the span
                       is a whole number of strobe periods. Control, exact: with the
                       compressor in use, whitening off and rate N_r, an aligned span
                       of 16 one-word outputs holds 16 strobes (the rate is ignored).
  CHK-COND-FIRST-PUSH  with the compressor bypassed and N_r written by the clean start
                       after the TRNG reset, the first FIFO word comes on the (N_r+1)th
                       strobe of ``esrc_stream_valid_gated_o`` (the stream after the boot
                       gate, architecture.adoc:40-47; entropy_source.adoc:106). Control:
                       no gated strobe before the clean start returned and no FIFO word
                       before the first gated strobe.
  CHK-COND-PERIOD-RATIO  with every lane disabled, D written, then the lanes enabled,
                       the steady gap g_D of ``esrc_decor_valid_o`` meets
                       g_D x (D_ref + 1) == g_ref x (D + 1) for D = 0 and D_r against the
                       reset value D_ref (entropy_source.adoc:387; architecture.adoc:107).
                       A ratio of two DUT gaps: no time base.
  CHK-COND-FIRST-STROBE  for D = D_ref, 0 and D_r, the distance from the clock where
                       ``esrc_ro_enable_o`` reads all ones to the first strobe equals the
                       steady gap g_D (architecture.adoc:113). Control: 6 strobes after
                       the enable, five equal gaps and no strobe while disabled.
  CHK-COND-SHA         16 whitener input words give 8 output words (architecture.adoc:142),
                       exact: over the span between the first and the last quiet clock
                       of the window (SHA256_STATUS BUSY = 0 and OUTPUT_COUNT = 0, no
                       input or output word within two clocks), 2 x output words ==
                       INPUT_COUNT(first) + input words - INPUT_COUNT(last). Input words
                       are strobes of ``esrc_whiten_push_o``; output words are strobes of
                       ``esrc_compress_vld_o``, the word written into the FIFO
                       (architecture.adoc:148); INPUT_COUNT is the words of the open
                       input block (entropy_source.adoc:207). At a quiet clock no digest
                       is in processing or output, so every block completed in the span
                       gave all its 8 words in the span. Control: at least one digest
                       (8 output words) and 16 input words in the span.
  CHK-COND-SHA-COUNT   OUTPUT_COUNT "reports 8 when a digest becomes available,
                       decrements through 0 as words are accepted, and remains 0 while
                       idle or bypassed" (entropy_source.adoc:206). In the whitened
                       window every OUTPUT_COUNT step of the status tap is -1 on a clock
                       after a FIFO word (``esrc_compress_vld_o``, no backpressure,
                       architecture.adoc:148), and a step without a word is only the
                       0 -> 8 of a new digest; each run from 8 holds exactly 8 steps
                       and ends at 0, and at least one run completes. In the
                       pass-through window OUTPUT_COUNT is 0 on every clock.
  CHK-COND-PASSTHRU    every FIFO word == BIW observe word i + d at one d in 0..8.
Logged only: ``OBS-BLOCKED CHK-COND-HT-OFF`` (the 32-bit health test with the
compressor bypassed has no single stated behaviour) and ``OBS-BLOCKED
CHK-COND-SHA-INTAKE`` (whether the whitener takes every BIW word is not stated).
``OBS-COND-PERIOD-ABS`` logs the gap of each divider value in ``clk_i`` cycles
(the time base of the period is not stated: the register text names sample-clock
cycles, the architecture text ``clk_i`` cycles). No text states the effect of a
``DOWNSAMPLE_RATE`` or ``SAMPLE_CLK_DIV`` write while the stream runs, of a rate
written while the stream is stopped, or where the downsample count starts when
the compressor bypass turns on: ``OBS-COND-DS-MIDRUN-UP``,
``OBS-COND-DS-MIDRUN-DOWN``, ``OBS-COND-DIV-MIDRUN-UP``,
``OBS-COND-DIV-MIDRUN-DOWN``, ``OBS-COND-DS-RESUME`` and ``OBS-COND-DS-BYPASS-ON``
log the tapped counts and the distance to the next strobe or FIFO word.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_esrc_pattern_noise import (
    NUM_LANES,
    Balanced,
    SepEsrcPatternNoise,
    Stuck,
    balanced_lanes,
    describe,
)
from env.sep_esrc_sha_tap import DIGEST_WORDS, SepEsrcShaTap
from env.sep_fcov_gate import (
    ESRC_CNT_PASS_FIRST_PUSH,
    ESRC_CNT_PASS_FIRST_STROBE,
    ESRC_CNT_PASS_PERIOD,
    close_graded_window,
    open_graded_window,
    set_esrc_cnt_pass,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, sym
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    ESRC_ALERT_THRESHOLD,
    ESRC_BIW_OBS_CTRL,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_DECORRELATOR_MASK,
    ESRC_FIFO_CTRL,
    ESRC_FIFO_RDATA,
    ESRC_FIFO_STATUS,
    ESRC_HEALTH_TEST_STATUS,
    ESRC_INTR_ENABLE,
    ESRC_INTR_STATUS,
    ESRC_RING_OSC_ENABLE,
)
from seq_lib.sep_esrc_clean_start_seq import (
    BYPASS_ALL,
    LATENCY_FACTOR,
    MAX_PRE_CLEAN_STROBES,
    PERIOD_CAP,
    RESET_STROBE_CLK,
    SepEsrcCleanStart,
    SepEsrcLeafSetup,
)

TEST = "sep_esrc_conditioning_matrix_rand_test"

ESRC_SHA256_STATUS = sym("ENTROPY_SOURCE_SHA256_STATUS_REG_ADDR")
ESRC_BIW_OBS_STATUS = sym("ENTROPY_SOURCE_BIW_OBS_STATUS_REG_ADDR")
ESRC_BIW_OBS_RDATA = sym("ENTROPY_SOURCE_BIW_OBS_RDATA_REG_ADDR")

# SW_RESET_N baseline 0x20: TRNG released; Key Manager and every engine held.
PARK = ("otbn", "aes", "hmac", "kmac", "abr")
LEGS = ("mask", "bypass", "downsample", "health", "whiten")
WINDOW = 2048
RATES_FIXED = (0, 1, 1023)
SIGNATURE_PASSES = (0, 1, 2, 3, "all1")
BYPASS_OUTPUTS = 21  # 63 words
MASK_STROBES = 16
SETTLE_STROBES = 4
SETTLE_CLOCKS = 29  # the 29-stage chain shifts on every clk_i
BYPASS_WORDS = 3  # FIFO words of one bypassed output (entropy_source.adoc:108)
SKIP_OUTPUTS = 2  # outputs after a rate write before the graded span starts
SPAN_OUTPUTS = 4  # outputs in one graded downsample span
CTRL_SPAN_OUTPUTS = 16  # BIW words in the compressor-on control span
SHA_BIW_MIN = 32
SHA_PUSH_MIN = 16
PASSTHRU_BIW_MIN = 16
PASSTHRU_FIFO_MIN = 8
PASSTHRU_MAX_OFFSET = 8
HT_WAIT_FACTOR = 3
# Period walk: strobes after a lane enable (the first distance and five gaps).
PERIOD_STROBES = 6
# Largest drawn divider value: a period walk value needs 7 periods of D + 1 clocks.
DIV_DRAW_MAX = 1023
# A rate above every drawn N_r (2 to 15), so N_r -> RATE_HI is an increase on every seed.
RATE_HI = 16
# Clocks the leaf holds a bit of esrc_cnt_pass before it writes 0.
CNT_HOLD_CLKS = 2
# Clocks from a RING_OSC_ENABLE write of 0 to esrc_ro_enable_o reading 0 (outer cap).
RO_OFF_CLKS = 64
# Outer cap of the mid-run trace (clocks); never a contract.
MIDRUN_CAP = 200_000

# Bounds. A latency bound is LAT_FACTOR x the clean time of the same operation
# measured earlier in the same run; the first measurement of a kind uses an
# outer cap only (SepEsrcLeafSetup.bound).
LAT_FACTOR = LATENCY_FACTOR
FIFO_DEPTH = 64

INTR_ENABLE_ALL = ENTROPY_SOURCE.mask("INTR_ENABLE")
_RO_ENABLE = ENTROPY_SOURCE.fields("RING_OSC_ENABLE")["ENABLE"]
# RING_OSC_ENABLE.ENABLE with every lane enabled (the reset value, entropy_source.adoc:357).
RO_ENABLE_ALL = _RO_ENABLE["bm"] >> _RO_ENABLE["bp"]


def _get(value: int, reg: str, field: str) -> int:
    meta = ENTROPY_SOURCE.fields(reg)[field]
    return (value & meta["bm"]) >> meta["bp"]


def _val(reg: str, **fields: int) -> int:
    return ENTROPY_SOURCE.value(reg, **fields)


# DECORRELATOR_CTRL.SAMPLE_CLK_DIV reset value, the reference of the period ratio.
RESET_DIV = _get(ENTROPY_SOURCE.reset("DECORRELATOR_CTRL"), "DECORRELATOR_CTRL", "SAMPLE_CLK_DIV")


def _lane_byte(bit: int, mask: int) -> int:
    return (0xFF if bit else 0x00) & mask


def _bypass_words(bits: list[int], mask: int) -> list[int]:
    """architecture.adoc:118: generator 4n+k in bits [8k+7:8k] of word n."""
    b = [_lane_byte(x, mask) for x in bits]
    return [sum(b[4 * n + k] << (8 * k) for k in range(4)) for n in range(3)]


@dataclass(frozen=True)
class Plan:
    seed: int
    legs: tuple[str, ...]
    mask: int
    n_r: int
    z: int
    balanced: tuple[Balanced, ...]
    div_r: int
    div_walk: tuple[int, ...]

    @property
    def rates(self) -> tuple[int, ...]:
        return tuple(sorted((0, 1, self.n_r, 1023)))

    def describe(self) -> str:
        return (
            f"legs={','.join(self.legs)} mask=0x{self.mask:02x} n_r={self.n_r} "
            f"z=0x{self.z:03x} rates={list(self.rates)} div_r={self.div_r} "
            f"div_walk={list(self.div_walk)} {describe(self.balanced)}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    legs = list(LEGS)
    rng.shuffle(legs)
    mask = rng.getrandbits(8)
    while not 0 < mask < 0xFF:
        mask = rng.getrandbits(8)
    n_r = rng.randrange(2, 16)
    z = rng.getrandbits(NUM_LANES)
    while z in (0, (1 << NUM_LANES) - 1):
        z = rng.getrandbits(NUM_LANES)
    if rng.getrandbits(1):
        z ^= (1 << NUM_LANES) - 1
    balanced = tuple(balanced_lanes(rng))
    div_r = rng.randrange(RESET_DIV + 1, DIV_DRAW_MAX + 1)
    tail = [0, div_r]
    rng.shuffle(tail)
    return Plan(seed, tuple(legs), mask, n_r, z, balanced, div_r, (RESET_DIV, *tail))


class _EsrcRegs(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


@pyuvm.test()
class sep_esrc_conditioning_matrix_rand_test(sep_base_test):
    """Mask, bypass packing, downsample and SHA-256 paths of the ESRC conditioning."""

    required_evidence = (
        "CHK-COND-MASK",
        "CHK-COND-BYPASS",
        "CHK-COND-DOWNSAMPLE",
        "CHK-COND-SHA",
        "CHK-COND-SHA-COUNT",
        "CHK-COND-PASSTHRU",
        "CHK-COND-FIRST-PUSH",
        "CHK-COND-PERIOD-RATIO",
        "CHK-COND-FIRST-STROBE",
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
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        # The testers and the window counter run from the TRNG reset release, so the
        # balanced noise runs before the first release and never stops.
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        self.noise.start(plan.balanced)
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)

        for leg in plan.legs:
            await getattr(self, f"_leg_{leg}")()
        close_graded_window(self.logger)
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

    async def _poll(self, addr: int, reg: str, field: str, pred, bound: int):
        """Reads until pred(field) holds or bound clocks pass: (ok, field, clocks)."""
        t0 = self._now()
        field_v = 0
        for _ in range(bound + 1):
            field_v = _get(await self._rd(addr), reg, field)
            if pred(field_v):
                return True, field_v, self._now() - t0
            if self._now() - t0 > bound:
                break
        return False, field_v, self._now() - t0

    async def _drain_fifo(self, status: str, rdata: int, status_addr: int) -> int:
        """Pop until LEVEL reads 0; at most the FIFO depth plus one pops."""
        pops = 0
        for _ in range(FIFO_DEPTH + 2):
            level = _get(await self._rd(status_addr), status, "LEVEL")
            if level == 0:
                return pops
            for _ in range(level):
                await self._rd(rdata)
                pops += 1
        raise AssertionError(f"{status}.LEVEL did not reach 0 after {pops} pops")

    # --- set-up -----------------------------------------------------------------
    async def _trng_reset(self) -> int:
        """TRNG reset 0 then 1 (SepEsrcLeafSetup); returns the noise mark at the release."""
        return await self.setup.trng_reset(balanced=self.plan.balanced)

    async def _setup(
        self, *, ctrl_fields: dict[str, int] | None = None, first_push: bool = False
    ) -> dict | None:
        """TRNG reset, clean start (with ``ctrl_fields`` in its CTRL writes), period, boot.

        With ``first_push`` a trace of the gated strobes and FIFO words runs from the
        TRNG reset release to the first FIFO word (``_first_push_trace``); the
        returned state holds it, with ``gated_at_ctrl`` = the gated strobes when the
        clean start returned, and ``task`` to await.
        """
        close_graded_window(self.logger)
        mark = await self._trng_reset()
        trace = None
        if first_push:
            # Outer cap: the boot bound of wait_boot_done, the strobes before the clean
            # start, two first-push distances and the period measurement.
            bound = (
                2 * WINDOW + 64 + MAX_PRE_CLEAN_STROBES + 2 * (self.plan.n_r + 1)
            ) * RESET_STROBE_CLK + PERIOD_CAP
            trace = {"g": 0, "pre_push": 0, "k": None, "ds_count": None, "reason": ""}
            trace["task"] = cocotb.start_soon(self._first_push_trace(trace, bound))
        await self._wr(ESRC_INTR_ENABLE, INTR_ENABLE_ALL)
        await self._wr(ESRC_ALERT_THRESHOLD, _val("ALERT_THRESHOLD", THRESHOLD=0))
        await SepEsrcCleanStart(
            self, self.noise, self.plan.balanced, window=WINDOW, ctrl_fields=ctrl_fields
        ).run(release_mark=mark)
        if trace is not None:
            trace["gated_at_ctrl"] = trace["g"]
        self.p = await self.setup.measure_period(self.chk)
        await self.setup.wait_boot_done(self.esrc, WINDOW)
        return trace

    async def _first_push_trace(self, st: dict, bound: int) -> None:
        """Counts ``esrc_stream_valid_gated_o`` strobes up to the first FIFO word.

        On every ``clk_i`` (ReadOnly): ``g`` counts the gated strobes; a word of
        ``esrc_compress_vld_o`` before the first gated strobe counts in ``pre_push``;
        the first word after it sets ``k`` = the gated strobes up to and including
        that clock and ``ds_count`` = ``esrc_downsample_count_o`` on that clock. A
        bypassed output writes its first word on the clock of its gated strobe, so
        ``k`` does not depend on a word latency. After ``bound`` clocks ``reason``
        names the timeout.
        """
        dut = cocotb.top
        for _ in range(bound):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.esrc_stream_valid_gated_o):
                st["g"] += 1
            if self.rd(dut.esrc_compress_vld_o):
                if st["g"] == 0:
                    st["pre_push"] += 1
                else:
                    st["k"] = st["g"]
                    st["ds_count"] = self.rd(dut.esrc_downsample_count_o)
                    break
        else:
            st["reason"] = f"timeout:first_push bound={bound}"
        await NextTimeStep()

    async def _cnt_pass(self, bits: int) -> None:
        """Pulse the esrc_cnt_pass bits of a check that passed (CNT_HOLD_CLKS)."""
        if set_esrc_cnt_pass(bits, self.logger):
            for _ in range(CNT_HOLD_CLKS):
                await RisingEdge(cocotb.top.clk_i)
            set_esrc_cnt_pass(0, self.logger)
            await RisingEdge(cocotb.top.clk_i)

    async def _drive_stuck(self, bits: list[int]) -> None:
        """Constant lane bits from the next strobe; waits >= 4 strobes and >= 29 clocks."""
        self.noise.set_lanes([Stuck(b) for b in bits])
        bound = (SETTLE_STROBES + 2) * self._period() * 4
        await self.noise.wait_words(1, bound)
        c_change = self.noise.strobe_clk
        await self.noise.wait_words(SETTLE_STROBES, bound)
        if self._now() - c_change < SETTLE_CLOCKS:
            await ClockCycles(cocotb.top.clk_i, SETTLE_CLOCKS)
        self.logger.info("SETTLE strobes=%d clocks=%d", SETTLE_STROBES, self._now() - c_change)

    async def _strobe_bytes(self, count: int, skip: int = 0) -> list[int]:
        """The 12 lane bytes of esrc_decor_bytes_o at each of ``count`` strobes after ``skip``."""
        dut = cocotb.top
        out: list[int] = []
        seen = 0
        for _ in range((count + skip + 2) * self._period() * 4):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.esrc_decor_valid_o):
                seen += 1
                if seen > skip:
                    out.append(self.rd(dut.esrc_decor_bytes_o))
                    if len(out) == count:
                        break
        await NextTimeStep()
        return out

    # --- mask leg -----------------------------------------------------------------
    async def _leg_mask(self) -> None:
        plan = self.plan
        await self._setup()
        open_graded_window(TEST, self.logger)
        await self._wr(ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL))
        await self._wr(ESRC_DECORRELATOR_MASK, _val("DECORRELATOR_MASK", ENTROPY_BYTE_MASK=0xFF))
        bits = [(plan.z >> j) & 1 for j in range(NUM_LANES)]
        await self._drive_stuck(bits)
        ff_bad = self._grade_mask(0xFF, bits, await self._strobe_bytes(MASK_STROBES))
        await self._wr(
            ESRC_DECORRELATOR_MASK, _val("DECORRELATOR_MASK", ENTROPY_BYTE_MASK=plan.mask)
        )
        self._grade_mask(plan.mask, bits, await self._strobe_bytes(MASK_STROBES, skip=2))
        self.chk.ctrl("COND-MASK", ff_bad == 0, mask_ff_mismatches=ff_bad)
        close_graded_window(self.logger)

    def _grade_mask(self, mask: int, bits: list[int], samples: list[int]) -> int:
        bad = 0
        for word in samples:
            for j in range(NUM_LANES):
                if (word >> (8 * j)) & 0xFF != _lane_byte(bits[j], mask):
                    bad += 1
        complete = len(samples) == MASK_STROBES
        self.chk.ok(
            "COND-MASK",
            complete and bad == 0,
            mask=f"0x{mask:02x}",
            noise=f"0x{self.plan.z:03x}",
            lanes=NUM_LANES,
            strobes=len(samples),
            mismatches=bad,
        )
        return bad if complete else bad + 1

    # --- bypass-words leg -----------------------------------------------------------
    async def _leg_bypass(self) -> None:
        plan = self.plan
        await self._setup()
        open_graded_window(TEST, self.logger)
        await self._wr(ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL))
        await self._wr(
            ESRC_DECORRELATOR_MASK, _val("DECORRELATOR_MASK", ENTROPY_BYTE_MASK=plan.mask)
        )
        await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=0))
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        for whiten in (1, 0):
            await self._wr(
                ESRC_CTRL,
                _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, SHA256_WHITENING_ENABLE=whiten),
            )
            for pas in SIGNATURE_PASSES:
                if not await self._bypass_pass(whiten, pas):
                    close_graded_window(self.logger)
                    return
        close_graded_window(self.logger)

    async def _bypass_pass(self, whiten: int, pas) -> bool:
        plan = self.plan
        bits = [1] * NUM_LANES if pas == "all1" else [(j >> pas) & 1 for j in range(NUM_LANES)]
        await self._drive_stuck(bits)
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE", ENABLE=0))
        await ClockCycles(cocotb.top.clk_i, 4)
        await self._drain_fifo("FIFO_STATUS", ESRC_FIFO_RDATA, ESRC_FIFO_STATUS)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))
        cap = (FIFO_DEPTH // 3 + 2) * self._period() * 20
        bound = self._bound("bypass_fill", cap)
        ok, level, clocks = await self._poll(
            ESRC_FIFO_STATUS, "FIFO_STATUS", "LEVEL", lambda v: v == FIFO_DEPTH, bound
        )
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        name = "all1" if pas == "all1" else str(pas)
        if not ok:
            self.chk.ok(
                "COND-BYPASS",
                False,
                whiten=whiten,
                pattern=name,
                level=level,
                reason=f"timeout:fifo_level bound={bound}",
            )
            return False
        self._learn("bypass_fill", clocks)
        words = [await self._rd(ESRC_FIFO_RDATA) for _ in range(3 * BYPASS_OUTPUTS)]
        expect = _bypass_words(bits, plan.mask)
        bad = sum(1 for i, w in enumerate(words) if w != expect[i % 3])
        self.chk.ok(
            "COND-BYPASS",
            bad == 0,
            whiten=whiten,
            mask=f"0x{plan.mask:02x}",
            pattern=name,
            outputs=BYPASS_OUTPUTS,
            words=len(words),
            mismatches=bad,
            first=",".join(f"0x{w:08x}" for w in words[:3]),
            expect=",".join(f"0x{w:08x}" for w in expect),
        )
        return True

    # --- downsample leg ---------------------------------------------------------------
    async def _leg_downsample(self) -> None:
        """Rate N: SPAN_OUTPUTS bypassed outputs take exactly (N+1) x SPAN_OUTPUTS strobes.

        entropy_source.adoc:106: DOWNSAMPLE_RATE = N selects every (N+1)th decorrelator
        output while BIW extraction is bypassed; entropy_source.adoc:108 and
        architecture.adoc:118: each selected output is three FIFO words. Control,
        compressor in use and whitening off: every decorrelator output is one BIW word
        (architecture.adoc:115) that reaches the FIFO unchanged (entropy_source.adoc:104),
        whatever the rate, so CTRL_SPAN_OUTPUTS words take exactly CTRL_SPAN_OUTPUTS
        strobes.

        The set-up writes the bypass and N_r in the clean start, so the first FIFO word
        after the TRNG reset is graded (``_grade_first_push``). After the control
        span the period walk (``_period_walk``) and the logged-only mid-run writes
        (``_midrun_obs``) run in the same graded window.
        """
        plan = self.plan
        trace = await self._setup(
            ctrl_fields={"BYPASS_ENTROPY_COMPRESSOR": 1, "DOWNSAMPLE_RATE": plan.n_r},
            first_push=True,
        )
        open_graded_window(TEST, self.logger)
        await self._grade_first_push(trace)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=0))
        results: list[tuple[int, dict]] = []
        prev = 0
        for n in plan.rates:
            await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=n))
            results.append((n, await self._aligned_span(BYPASS_WORDS, SPAN_OUTPUTS, n, prev)))
            prev = n
        await self._wr(ESRC_CTRL, _val("CTRL", DOWNSAMPLE_RATE=plan.n_r, SHA256_WHITENING_ENABLE=0))
        c = await self._aligned_span(1, CTRL_SPAN_OUTPUTS, 0, prev)
        await self._period_walk()
        await self._midrun_obs()
        close_graded_window(self.logger)
        self.chk.ctrl(
            "COND-DOWNSAMPLE",
            c["aligned"] and c["strobes"] == CTRL_SPAN_OUTPUTS and c["words"] == CTRL_SPAN_OUTPUTS,
            bypass=0,
            whiten=0,
            rate=plan.n_r,
            expect_strobes=CTRL_SPAN_OUTPUTS,
            **{k: v for k, v in c.items() if k != "aligned"},
        )
        for n, r in results:
            expect = (n + 1) * SPAN_OUTPUTS
            fields = {
                "n": n,
                "bypass": 1,
                "outputs": SPAN_OUTPUTS,
                "expect_strobes": expect,
                **{k: v for k, v in r.items() if k != "aligned"},
            }
            ok = (
                r["aligned"]
                and r["strobes"] == expect
                and r["words"] == BYPASS_WORDS * SPAN_OUTPUTS
            )
            if not r["aligned"] and "reason" not in fields:
                fields["reason"] = "span_not_aligned"
            self.chk.ok("COND-DOWNSAMPLE", ok, **fields)

    async def _aligned_span(self, per_output: int, outputs: int, n: int, prev: int) -> dict:
        """Strobes and words between the ends of two outputs, ``outputs`` outputs apart.

        One output is the words on ``esrc_compress_vld_o`` with no strobe of
        ``esrc_decor_valid_o`` between them; a strobe closes the open output (a strobe
        and a word on one clock: the strobe first). The span runs from the clock of the
        last word of output SKIP_OUTPUTS (counted from the rate write response) to the
        clock of the last word of output SKIP_OUTPUTS + ``outputs``; it counts the
        strobes after its first clock up to and including its last clock.

        The span is aligned when every output in it has ``per_output`` words, every
        strobe gap from the last strobe before the span to its end is one value P, and
        both ends lie the same number of clocks after their last strobe. Then the span
        is a whole number of strobe periods and the strobe count is exact: it does not
        depend on the latency from a strobe to its words.
        """
        dut = cocotb.top
        reach = (prev + 1) + (SKIP_OUTPUTS + outputs + 2) * (n + 1) + 8
        clock_cap = 4 * reach * self._period()
        need = SKIP_OUTPUTS + outputs
        clk = 0
        strobes = 0
        strobe_clks: list[int] = []
        groups: list[tuple[int, int, int]] = []  # (words, last word clock, strobes then)
        cur: list[int] | None = None
        reason = ""
        while len(groups) < need:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            clk += 1
            if clk > clock_cap:
                reason = f"timeout:outputs clock_bound={clock_cap} outputs_seen={len(groups)}"
                break
            if self.rd(dut.esrc_decor_valid_o):
                strobes += 1
                strobe_clks.append(clk)
                if cur is not None:
                    groups.append((cur[0], cur[1], cur[2]))
                    cur = None
            if self.rd(dut.esrc_compress_vld_o):
                if cur is None:
                    cur = [0, clk, strobes]
                cur[0] += 1
                cur[1] = clk
                cur[2] = strobes
        await NextTimeStep()
        out = {"strobes": "none", "words": "none", "sizes": [], "phase": "na", "gaps": []}
        if len(groups) < need:
            out["aligned"] = False
            out["reason"] = reason
            return out
        a, b = groups[SKIP_OUTPUTS - 1], groups[need - 1]
        span = groups[SKIP_OUTPUTS:need]
        sizes = [g[0] for g in span]
        last_a = max(s for s in strobe_clks if s <= a[1])
        last_b = max(s for s in strobe_clks if s <= b[1])
        in_span = [s for s in strobe_clks if last_a <= s <= b[1]]
        gaps = sorted({y - x for x, y in zip(in_span, in_span[1:])})
        phases = (a[1] - last_a, b[1] - last_b)
        aligned = all(s == per_output for s in sizes) and len(gaps) <= 1 and phases[0] == phases[1]
        out.update(
            {
                "aligned": aligned,
                "strobes": b[2] - a[2],
                "words": sum(sizes),
                "sizes": sizes,
                "phase": f"{phases[0]}_{phases[1]}",
                "gaps": gaps,
                "span_clk": b[1] - a[1],
            }
        )
        return out

    # --- first push, period walk and mid-run writes (downsample leg) -------------
    async def _grade_first_push(self, trace: dict) -> None:
        """CHK-COND-FIRST-PUSH: the first FIFO word on the (N_r+1)th gated strobe.

        entropy_source.adoc:106: DOWNSAMPLE_RATE = N selects every (N+1)th
        decorrelator output while BIW extraction is bypassed; architecture.adoc:40-47:
        the boot gate passes the uncompressed bytes only after a passing boot window,
        and the output select downsamples them by DOWNSAMPLE_RATE. The register block
        and the downsample count share the TRNG reset; the clean start writes N_r and
        the bypass before the boot gate passes any strobe, so the count of selected
        outputs starts at the first gated strobe. Anchor: ``esrc_stream_valid_gated_o``
        and ``esrc_compress_vld_o``; the clean start is the only stimulus.
        """
        plan = self.plan
        await trace["task"]
        k = trace["k"]
        expect = plan.n_r + 1
        fields = {
            "n": plan.n_r,
            "first_push_gated": "none" if k is None else k,
            "expect": expect,
            "gated_at_ctrl": trace["gated_at_ctrl"],
            "pre_push": trace["pre_push"],
            "ds_count": "none" if trace["ds_count"] is None else trace["ds_count"],
        }
        if trace["reason"]:
            fields["reason"] = trace["reason"]
        self.chk.ctrl(
            "COND-FIRST-PUSH",
            trace["gated_at_ctrl"] == 0 and trace["pre_push"] == 0 and plan.n_r >= 1,
            gated_at_ctrl=trace["gated_at_ctrl"],
            pre_push=trace["pre_push"],
            n=plan.n_r,
        )
        if self.chk.ok("COND-FIRST-PUSH", k == expect, **fields):
            await self._cnt_pass(ESRC_CNT_PASS_FIRST_PUSH)

    async def _lanes_off(self) -> int | None:
        """RING_OSC_ENABLE.ENABLE = 0; clocks until ``esrc_ro_enable_o`` reads 0, or None."""
        dut = cocotb.top
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE", ENABLE=0))
        return await self.setup.wait_probe(lambda: self.rd(dut.esrc_ro_enable_o) == 0, RO_OFF_CLKS)

    async def _set_div(self, div: int) -> None:
        """Lanes off, SAMPLE_CLK_DIV = ``div``, lanes on; raises if the lanes do not stop.

        The order of ``doc/programmer/src/sep-programming.adoc:409-411,427``.
        """
        if await self._lanes_off() is None:
            raise AssertionError(f"esrc_ro_enable_o not 0 bound={RO_OFF_CLKS}")
        await self._wr(
            ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL, SAMPLE_CLK_DIV=div)
        )
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))

    async def _enable_trace(self, st: dict, bound: int) -> None:
        """Strobes of ``esrc_decor_valid_o`` around the lane enable, on every clk_i.

        ``e0`` is the first clock where ``esrc_ro_enable_o`` reads every lane enabled,
        and ``div_tap`` is ``esrc_decor_div_lane0_o`` on that clock; ``pre`` counts the
        strobes up to and including it; ``strobes`` holds the clocks of the first
        PERIOD_STROBES strobes after it. After ``bound`` clocks ``reason`` names the
        timeout.
        """
        dut = cocotb.top
        for clk in range(1, bound + 1):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            strobe = self.rd(dut.esrc_decor_valid_o)
            if st["e0"] is None:
                st["pre"] += strobe
                if self.rd(dut.esrc_ro_enable_o) == RO_ENABLE_ALL:
                    st["e0"] = clk
                    st["div_tap"] = self.rd(dut.esrc_decor_div_lane0_o)
                continue
            if strobe:
                st["strobes"].append(clk)
                if len(st["strobes"]) == PERIOD_STROBES:
                    break
        else:
            st["reason"] = f"timeout:strobes bound={bound} seen={len(st['strobes'])}"
        await NextTimeStep()

    async def _walk_one(self, div: int) -> dict:
        """Lanes off, SAMPLE_CLK_DIV = ``div``, then the lane enable under the trace."""
        off = await self._lanes_off()
        await self._wr(
            ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL, SAMPLE_CLK_DIV=div)
        )
        st = {"e0": None, "pre": 0, "div_tap": None, "strobes": [], "reason": ""}
        if off is None:
            st["reason"] = f"timeout:enable_off bound={RO_OFF_CLKS}"
        task = cocotb.start_soon(self._enable_trace(st, 8 * (div + 1) + 256))
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))
        await task
        s = st["strobes"]
        e0 = st["e0"]
        st["first"] = s[0] - e0 if s and e0 is not None else None
        st["gaps"] = [b - a for a, b in zip(s, s[1:])]
        st["ok"] = (
            off is not None
            and e0 is not None
            and st["pre"] == 0
            and len(s) == PERIOD_STROBES
            and len(set(st["gaps"])) == 1
        )
        st["gap"] = st["gaps"][0] if st["ok"] else None
        return st

    async def _period_walk(self) -> None:
        """CHK-COND-PERIOD-RATIO and CHK-COND-FIRST-STROBE over D_ref, then 0 and D_r.

        entropy_source.adoc:387 and architecture.adoc:107: the byte period is
        SAMPLE_CLK_DIV + 1 cycles, so the steady gaps of two values D and D_ref meet
        g_D x (D_ref + 1) == g_ref x (D + 1) whatever the unit of a cycle.
        architecture.adoc:113: while ``enable_i`` is low the divider holds at zero,
        so a value written before the enable sets the first distance: one full
        period, the steady gap. The enable of a lane is RING_OSC_ENABLE.ENABLE
        (entropy_source.adoc:357); each value is written with every lane disabled
        and then the lanes are enabled, the order of
        ``doc/programmer/src/sep-programming.adoc:409-411,427``. Anchor:
        ``esrc_ro_enable_o`` and ``esrc_decor_valid_o``.
        """
        plan = self.plan
        await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=0))
        ref: dict | None = None
        ratio_pass = 0
        for div in plan.div_walk:
            st = await self._walk_one(div)
            self.chk.ctrl(
                "COND-PERIOD",
                st["ok"],
                div=div,
                strobes=len(st["strobes"]),
                gaps=sorted(set(st["gaps"])),
                enable_rose=st["e0"] is not None,
                pre_enable_strobes=st["pre"],
                **({"reason": st["reason"]} if st["reason"] else {}),
            )
            self.chk.obs(
                "COND-PERIOD-ABS", div=div, period_clk="none" if st["gap"] is None else st["gap"]
            )
            self.logger.info(
                "INFO-COND-DIV-TAP seed=%d div=%d div_tap_at_enable=%s",
                plan.seed,
                div,
                "none" if st["div_tap"] is None else st["div_tap"],
            )
            first_ok = self.chk.ok(
                "COND-FIRST-STROBE",
                st["ok"] and st["first"] == st["gap"],
                div=div,
                first_clk="none" if st["first"] is None else st["first"],
                gap_clk="none" if st["gap"] is None else st["gap"],
            )
            if first_ok:
                await self._cnt_pass(ESRC_CNT_PASS_FIRST_STROBE)
            if div == RESET_DIV:
                ref = st
                continue
            g = st["gap"]
            g_ref = None if ref is None else ref["gap"]
            lhs = None if g is None else g * (RESET_DIV + 1)
            rhs = None if g_ref is None else g_ref * (div + 1)
            if self.chk.ok(
                "COND-PERIOD-RATIO",
                lhs is not None and rhs is not None and lhs == rhs,
                div=div,
                ref_div=RESET_DIV,
                gap="none" if g is None else g,
                ref_gap="none" if g_ref is None else g_ref,
                lhs="none" if lhs is None else lhs,
                rhs="none" if rhs is None else rhs,
            ):
                ratio_pass += 1
                await self._cnt_pass(ESRC_CNT_PASS_PERIOD)
        await self._set_div(RESET_DIV)
        if ratio_pass == len(plan.div_walk) - 1:
            # The reference value of both passing ratios, while it is stored.
            await self._cnt_pass(ESRC_CNT_PASS_PERIOD)

    # --- mid-run writes (logged only) -------------------------------------------------
    async def _tap_trace(self, rows: list, run: list) -> None:
        """One row per clk_i (ReadOnly): (strobe, gated strobe, FIFO word, ds count, div count)."""
        dut = cocotb.top
        while run[0] and len(rows) < MIDRUN_CAP:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            rows.append(
                (
                    self.rd(dut.esrc_decor_valid_o),
                    self.rd(dut.esrc_stream_valid_gated_o),
                    self.rd(dut.esrc_compress_vld_o),
                    self.rd(dut.esrc_downsample_count_o),
                    self.rd(dut.esrc_decor_div_lane0_o),
                )
            )
        await NextTimeStep()

    async def _wait_row(
        self, rows: list, start: int, pred, bound: int, count: int = 1
    ) -> list[int]:
        """Indexes of the first ``count`` rows from ``start`` on where pred(row) holds.

        Waits at most ``bound`` clocks; returns fewer indexes on a timeout.
        """
        hits: list[int] = []
        i = start
        for _ in range(bound + 1):
            while i < len(rows):
                if pred(rows[i]):
                    hits.append(i)
                    if len(hits) == count:
                        return hits
                i += 1
            await RisingEdge(cocotb.top.clk_i)
        return hits

    @staticmethod
    def _to_push(rows: list, start: int) -> dict:
        """Gated strobes from row ``start`` up to and including the first FIFO word."""
        for j in range(start, len(rows)):
            if rows[j][2]:
                return {
                    "gated_to_push": sum(r[1] for r in rows[start : j + 1]),
                    "ds_count_at_push": rows[j][3],
                }
        return {"gated_to_push": "none", "ds_count_at_push": "none"}

    async def _div_write(self, rows: list, before: int, after: int, tag: str) -> None:
        """A SAMPLE_CLK_DIV write right after a strobe, lanes running; logs ``tag``.

        ``div_tap_at_fire`` is the lane 0 divider count on the clock before the first
        strobe after the write, the count that met the compare.
        """
        sync = await self._wait_row(rows, len(rows), lambda r: r[0], 4 * (before + 1) + 64)
        i_s = sync[0] if sync else len(rows) - 1
        await self._wr(
            ESRC_DECORRELATOR_CTRL,
            _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL, SAMPLE_CLK_DIV=after),
        )
        i_w = len(rows) - 1
        bound = 4 * (max(before, after) + 1) + 64
        s = await self._wait_row(rows, i_s + 1, lambda r: r[0], bound, count=2)
        tap_fire = rows[s[0] - 1][4] if s else None
        fields = {
            "div_before": before,
            "div_after": after,
            "div_tap_at_resp": rows[i_w][4],
            "div_tap_at_fire": "none" if tap_fire is None else tap_fire,
            "below_count": "none" if tap_fire is None else int(tap_fire > after),
            "first_gap": s[0] - i_s if s else "none",
            "steady_gap": s[1] - s[0] if len(s) == 2 else "none",
        }
        if not sync or len(s) < 2:
            fields["reason"] = "timeout:strobes"
        self.chk.obs(tag, **fields)

    async def _rate_write(self, rows: list, before: int, after: int, tag: str, sync) -> None:
        """A DOWNSAMPLE_RATE write, compressor bypassed, once a row meets ``sync``; logs ``tag``.

        ``below_count`` is 1 when the downsample count at the first FIFO word after
        the write is above the new rate.
        """
        p = RESET_DIV + 1
        hit = await self._wait_row(rows, len(rows), sync, (2 * RATE_HI + 4) * p * 4)
        await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=after))
        i_w = len(rows) - 1
        await self._wait_row(rows, i_w + 1, lambda r: r[2], (max(before, after) + 2) * p * 4)
        fields = {
            "rate_before": before,
            "rate_after": after,
            "ds_count_at_resp": rows[i_w][3],
            **self._to_push(rows, i_w + 1),
        }
        c = fields["ds_count_at_push"]
        fields["below_count"] = "none" if c == "none" else int(c > after)
        if not hit:
            fields["reason"] = "timeout:sync"
        self.chk.obs(tag, **fields)

    async def _midrun_obs(self) -> None:
        """Mid-run DOWNSAMPLE_RATE and SAMPLE_CLK_DIV writes, a rate written while stopped,
        and the bypass turned on while the gated stream runs: logged only.

        No text states the effect of these writes, so every line is ``OBS-``. Each
        line logs the stored value before and after, the tapped count
        (``esrc_downsample_count_o``, ``esrc_decor_div_lane0_o``) and the distance to
        the next strobe or FIFO word. A count above the new stored value is the
        ``below_count`` case.
        """
        plan = self.plan
        p = RESET_DIV + 1
        rows: list = []
        run = [True]
        task = cocotb.start_soon(self._tap_trace(rows, run))

        # SAMPLE_CLK_DIV with the lanes running: up, down to at or above the count,
        # up again, down below the count (0 while the count is above 0).
        await self._div_write(rows, RESET_DIV, plan.div_r, "COND-DIV-MIDRUN-UP")
        await self._div_write(rows, plan.div_r, RESET_DIV, "COND-DIV-MIDRUN-DOWN")
        await self._div_write(rows, RESET_DIV, plan.div_r, "COND-DIV-MIDRUN-UP")
        await self._div_write(rows, plan.div_r, 0, "COND-DIV-MIDRUN-DOWN")
        await self._set_div(RESET_DIV)

        # The bypass turned on at rate N_r while the gated stream runs, whitening off.
        await self._wr(ESRC_CTRL, _val("CTRL", DOWNSAMPLE_RATE=plan.n_r, SHA256_WHITENING_ENABLE=0))
        await self._wait_row(
            rows, len(rows), lambda r: r[1], (plan.n_r + 6) * p * 4, count=plan.n_r + 3
        )
        await self._wr(
            ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=plan.n_r)
        )
        i_w = len(rows) - 1
        await self._wait_row(rows, i_w + 1, lambda r: r[2], (plan.n_r + 2) * p * 4)
        self.chk.obs(
            "COND-DS-BYPASS-ON",
            rate=plan.n_r,
            ds_count_at_resp=rows[i_w][3],
            **self._to_push(rows, i_w + 1),
        )

        # DOWNSAMPLE_RATE with the compressor bypassed: up, down below the count,
        # up, down to at or above the count (right after a word), up.
        def word(r):
            return r[2]

        await self._rate_write(rows, plan.n_r, RATE_HI, "COND-DS-MIDRUN-UP", word)
        await self._rate_write(rows, RATE_HI, 0, "COND-DS-MIDRUN-DOWN", lambda r: r[3] >= 2)
        await self._rate_write(rows, 0, RATE_HI, "COND-DS-MIDRUN-UP", word)
        await self._rate_write(rows, RATE_HI, 1, "COND-DS-MIDRUN-DOWN", word)
        await self._rate_write(rows, 1, RATE_HI, "COND-DS-MIDRUN-UP", word)

        # A rate written while the gated stream is stopped (every lane off), then resume.
        hit = await self._wait_row(
            rows, len(rows), lambda r: 1 <= r[3] < RATE_HI - 1, (2 * RATE_HI + 4) * p * 4
        )
        off = await self._lanes_off()
        held = rows[-1][3]
        await self._wr(
            ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=plan.n_r)
        )
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))
        i_e = len(rows) - 1
        await self._wait_row(rows, i_e + 1, lambda r: r[2], (RATE_HI + 2) * p * 4)
        fields = {
            "rate_before": RATE_HI,
            "rate_after": plan.n_r,
            "ds_count_held": held,
            **self._to_push(rows, i_e + 1),
        }
        if not hit:
            fields["reason"] = "timeout:sync"
        elif off is None:
            fields["reason"] = f"timeout:enable_off bound={RO_OFF_CLKS}"
        self.chk.obs("COND-DS-RESUME", **fields)

        run[0] = False
        await task
        await self._wr(ESRC_CTRL, _val("CTRL"))

    # --- health-test leg (logged only) ----------------------------------------------
    async def _leg_health(self) -> None:
        await self._setup()
        await self._wr(ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL))
        await self._wr(ESRC_HEALTH_TEST_STATUS, _val("HEALTH_TEST_STATUS", HEALTH_STATUS=0xFF))
        s_ctrl0 = await self._rd(ESRC_HEALTH_TEST_STATUS)
        self.noise.set_lanes([Stuck(0)] * NUM_LANES)
        bound = (WINDOW + 256) * self._period()
        ok, _, t_ctrl = await self._poll(
            ESRC_HEALTH_TEST_STATUS, "HEALTH_TEST_STATUS", "HEALTH_STATUS", lambda v: v & 1, bound
        )
        self.chk.obs(
            "COND-HT-CTRL",
            bypass=0,
            ht_status_before=f"0x{s_ctrl0:08x}",
            rep_set=ok,
            t_ctrl_clk=t_ctrl,
            bound=bound,
        )
        await self._setup()
        await self._wr(ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL))
        await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1))
        await self._wr(ESRC_HEALTH_TEST_STATUS, _val("HEALTH_TEST_STATUS", HEALTH_STATUS=0xFF))
        s_before = await self._rd(ESRC_HEALTH_TEST_STATUS)
        self.noise.set_lanes([Stuck(0)] * NUM_LANES)
        wait = HT_WAIT_FACTOR * max(1, t_ctrl)
        await ClockCycles(cocotb.top.clk_i, wait)
        s_after = await self._rd(ESRC_HEALTH_TEST_STATUS)
        self.chk.blocked("COND-HT-OFF", "ht32_in_bypass_unstated")
        self.chk.obs(
            "COND-HT-OFF",
            bypass=1,
            ht_status_before=f"0x{s_before:08x}",
            ht_status=f"0x{s_after:08x}",
            t_ctrl_clk=t_ctrl,
            wait_clk=wait,
        )

    # --- whitener and pass-through leg ---------------------------------------------
    async def _leg_whiten(self) -> None:
        await self._setup()
        open_graded_window(TEST, self.logger)
        await self._wr(ESRC_CTRL, _val("CTRL"))
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._drain_fifo("FIFO_STATUS", ESRC_FIFO_RDATA, ESRC_FIFO_STATUS)

        white = SepEsrcShaTap(self.rd).start()
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=1))
        push0 = white.pushes
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        cap = SHA_BIW_MIN * 4 * self._period() * 20
        ok, biw_seen, _, sha_reads = await self._poll_biw(SHA_BIW_MIN, cap)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        pushes = white.pushes - push0
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))
        await white.stop()
        self.chk.obs(
            "COND-SHA-STATUS-READS", reads=len(sha_reads), values=[f"0x{v:x}" for v in sha_reads]
        )
        biw = _get(await self._rd(ESRC_BIW_OBS_STATUS), "BIW_OBS_STATUS", "LEVEL")
        fifo = _get(await self._rd(ESRC_FIFO_STATUS), "FIFO_STATUS", "LEVEL")
        intr = await self._rd(ESRC_INTR_STATUS)
        ovf = _get(intr, "INTR_STATUS", "BIW_OBS_OVERFLOW")
        self.chk.ctrl(
            "COND-SHA",
            ok and ovf == 0 and biw > 0 and fifo > 0,
            biw_words=biw,
            fifo_words=fifo,
            biw_obs_overflow=ovf,
            biw_level_reached=ok,
        )
        span = white.quiet_span()
        s = span or {"span_clk": 0, "in_first": 0, "in_last": 0, "in_words": 0, "out_words": 0}
        self.chk.ctrl(
            "COND-SHA",
            span is not None and s["out_words"] >= DIGEST_WORDS and s["in_words"] >= SHA_PUSH_MIN,
            pushes=pushes,
            span_in_words=s["in_words"],
            span_out_words=s["out_words"],
            min_in=SHA_PUSH_MIN,
            min_out=DIGEST_WORDS,
        )
        absorbed = s["in_first"] + s["in_words"] - s["in_last"]
        fields = {
            "expected_out_x2": absorbed,
            "out_words_x2": 2 * s["out_words"],
            "in_words": s["in_words"],
            "input_count_first": s["in_first"],
            "input_count_last": s["in_last"],
            "span_clk": s["span_clk"],
            "fifo_words": fifo,
            "biw_words": biw,
        }
        if not ok:
            fields["reason"] = f"timeout:biw_level bound={cap}"
        elif span is None:
            fields["reason"] = "no_quiet_span"
        self.chk.ok(
            "COND-SHA",
            ok and span is not None and 2 * s["out_words"] == absorbed,
            **fields,
        )
        self.chk.blocked("COND-SHA-INTAKE", "whitener_intake_while_hashing_unstated")
        self.chk.obs("COND-SHA-INTAKE", biw_words=biw, pushes=pushes, fifo_words=fifo)

        # Pass-through, in the same trial.
        await self._drain_fifo("FIFO_STATUS", ESRC_FIFO_RDATA, ESRC_FIFO_STATUS)
        await self._drain_fifo("BIW_OBS_STATUS", ESRC_BIW_OBS_RDATA, ESRC_BIW_OBS_STATUS)
        await self._wr(ESRC_CTRL, _val("CTRL", SHA256_WHITENING_ENABLE=0))
        busy_cap = DIGEST_WORDS * 64 * self._period()
        busy_ok, _, _ = await self._poll(
            ESRC_SHA256_STATUS, "SHA256_STATUS", "BUSY", lambda v: v == 0, busy_cap
        )
        pass_tap = SepEsrcShaTap(self.rd).start()
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=1))
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        p_ok, _, _, out_reads = await self._poll_biw(PASSTHRU_BIW_MIN, cap)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))
        await pass_tap.stop()
        # The tap task ends in ReadOnly; a gate write needs the next time step.
        await NextTimeStep()
        close_graded_window(self.logger)

        fifo_level = _get(await self._rd(ESRC_FIFO_STATUS), "FIFO_STATUS", "LEVEL")
        biw_level = _get(await self._rd(ESRC_BIW_OBS_STATUS), "BIW_OBS_STATUS", "LEVEL")
        biw_words = [await self._rd(ESRC_BIW_OBS_RDATA) for _ in range(biw_level)]
        fifo_words = [await self._rd(ESRC_FIFO_RDATA) for _ in range(fifo_level)]
        self.chk.ctrl(
            "COND-PASSTHRU",
            busy_ok and p_ok and fifo_level >= PASSTHRU_FIFO_MIN,
            fifo_level=fifo_level,
            busy_zero=busy_ok,
            biw_level_reached=p_ok,
        )
        offset = None
        for d in range(PASSTHRU_MAX_OFFSET + 1):
            if len(fifo_words) + d <= len(biw_words) and all(
                w == biw_words[i + d] for i, w in enumerate(fifo_words)
            ):
                offset = d
                break
        self.chk.ok(
            "COND-PASSTHRU",
            bool(fifo_words) and offset is not None,
            offset="none" if offset is None else offset,
            compared=len(fifo_words),
            biw_words=len(biw_words),
            mismatches=0 if offset is not None else "all_offsets",
        )
        outs = [_get(v, "SHA256_STATUS", "OUTPUT_COUNT") for v in out_reads]
        self.chk.obs("COND-PASSTHRU-OUTCOUNT", reads=len(outs), nonzero=sum(1 for o in outs if o))

        walk = white.output_count_walk()
        runs = walk["runs"]
        errors = walk["errors"]
        self.chk.ctrl(
            "COND-SHA-COUNT", biw > 0 and walk["steps"] > 0, biw_words=biw, steps=walk["steps"]
        )
        self.chk.ok(
            "COND-SHA-COUNT",
            not errors
            and len(runs) >= 1
            and all(r == DIGEST_WORDS for r in runs)
            and white.out_max == DIGEST_WORDS
            and pass_tap.out_max == 0
            and pass_tap.clocks > 0,
            steps=walk["steps"],
            runs_complete=len(runs),
            min_runs=1,
            run_steps=runs,
            expected_run_steps=DIGEST_WORDS,
            open_run_steps=walk["open_run_steps"],
            step_errors=len(errors),
            first_errors=errors[:4],
            out_count_max=white.out_max,
            out_count_end=white.out_last,
            biw_words=biw,
            bypass_out_count_max=pass_tap.out_max,
            bypass_clocks=pass_tap.clocks,
        )

    async def _poll_biw(self, minimum: int, bound: int):
        """Poll BIW_OBS_STATUS.LEVEL >= minimum; reads SHA256_STATUS after each poll."""
        t0 = self._now()
        sha: list[int] = []
        level = 0
        for _ in range(bound + 1):
            level = _get(await self._rd(ESRC_BIW_OBS_STATUS), "BIW_OBS_STATUS", "LEVEL")
            sha.append(await self._rd(ESRC_SHA256_STATUS))
            if level >= minimum:
                return True, level, self._now() - t0, sha
            if self._now() - t0 > bound:
                break
        return False, level, self._now() - t0, sha
