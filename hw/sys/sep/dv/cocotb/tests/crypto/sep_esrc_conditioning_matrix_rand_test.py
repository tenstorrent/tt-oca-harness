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
noise Z (12 bits with a 0 and a 1) and its polarity, and the balanced lanes.

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
from env.sep_fcov_gate import close_graded_window, open_graded_window
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

# Bounds. A latency bound is LAT_FACTOR x the clean time of the same operation
# measured earlier in the same run; the first measurement of a kind uses an
# outer cap only (SepEsrcLeafSetup.bound).
LAT_FACTOR = LATENCY_FACTOR
FIFO_DEPTH = 64

INTR_ENABLE_ALL = ENTROPY_SOURCE.mask("INTR_ENABLE")


def _get(value: int, reg: str, field: str) -> int:
    meta = ENTROPY_SOURCE.fields(reg)[field]
    return (value & meta["bm"]) >> meta["bp"]


def _val(reg: str, **fields: int) -> int:
    return ENTROPY_SOURCE.value(reg, **fields)


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

    @property
    def rates(self) -> tuple[int, ...]:
        return tuple(sorted((0, 1, self.n_r, 1023)))

    def describe(self) -> str:
        return (
            f"legs={','.join(self.legs)} mask=0x{self.mask:02x} n_r={self.n_r} "
            f"z=0x{self.z:03x} rates={list(self.rates)} {describe(self.balanced)}"
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
    return Plan(seed, tuple(legs), mask, n_r, z, balanced)


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

    async def _setup(self) -> None:
        close_graded_window(self.logger)
        mark = await self._trng_reset()
        await self._wr(ESRC_INTR_ENABLE, INTR_ENABLE_ALL)
        await self._wr(ESRC_ALERT_THRESHOLD, _val("ALERT_THRESHOLD", THRESHOLD=0))
        await SepEsrcCleanStart(self, self.noise, self.plan.balanced, window=WINDOW).run(
            release_mark=mark
        )
        self.p = await self.setup.measure_period(self.chk)
        await self.setup.wait_boot_done(self.esrc, WINDOW)

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
        """
        plan = self.plan
        await self._setup()
        open_graded_window(TEST, self.logger)
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
