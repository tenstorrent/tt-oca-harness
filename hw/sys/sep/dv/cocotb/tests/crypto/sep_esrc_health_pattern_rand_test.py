# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC per-lane health testers under exact lane patterns, and the 32-bit tester.

Contract (``hw/ip/entropy_source/doc/architecture.adoc`` Health Testing and SHA-256
Whitening; ``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc``):
  * Each of the 12 generators runs the repetition, adaptive-proportion (APT) and
    Markov testers on its own byte stream, with one shared set of limits and
    one shared window (architecture.adoc:122, :124, :126). A failure latches
    ``GENERATOR_n_HEALTH_STATUS`` with the ``HEALTH_TEST_STATUS`` allocation:
    bit 0 repetition, bit 3 APT, bits 4 and 5 Markov high and low
    (architecture.adoc:126; entropy_source.adoc:423).
  * ``HEALTH_TEST_CTRL.ENABLE`` bits 0, 1 and 2 enable the repetition, APT and
    Markov testers; disabling a tester clears its state (entropy_source.adoc:256).
  * ``REPETITION_LIMIT`` is the maximum run, ``PROB_01_THRESHOLD`` the maximum and
    ``PROB_10_THRESHOLD`` the minimum alternation count, ``APT_PROPORTION_1BIT``
    the maximum and ``APT_PROPORTION_LO`` the minimum one count per lane
    (entropy_source.adoc:254, :275, :276, :326, :336).
  * The generator status is RW1C (entropy_source.adoc:423).
  * ``HEALTH_TEST_STATUS`` latches the failures of the 32-bit stream tester; bit 3
    is APT high or low (entropy_source.adoc:27). ``APT_PROPORTION_LO`` = 0
    disables the low-side test (entropy_source.adoc:336).
  * A constant-zero 32-bit stream fails the low APT and the low Markov tests:
    ``HEALTH_TEST_STATUS`` bits 3 and 5, ``APT_LO_TOTAL_FAILS``,
    ``MARKOV_LO_TOTAL_FAILS`` and ``INTR_STATUS.HEALTH_TEST_FAILED``
    (entropy_source.adoc:68, :70, :148). With the low side disabled, a constant
    word with a lane at 1 fails the 32-bit APT high test: bit 3. It also makes
    ``APT_HI_TOTAL_FAILS`` non-zero (entropy_source.adoc:67, :326); which tester
    instances that counter counts is not stated.
  * The BIW stage computes y = a*b + c in GF(2^8) on the 12 lane bytes
    (architecture.adoc:115), so constant-zero lanes give a zero 32-bit word: its
    one count and alternation count are 0, below the maximum one count
    (``APT_PROPORTION_1BIT``, entropy_source.rdl:394) and the maximum alternation
    count (``PROB_01_THRESHOLD``, entropy_source.rdl:340). No high-side test fails:
    ``HEALTH_TEST_STATUS`` bit 4 (architecture.adoc:126), ``APT_HI_TOTAL_FAILS`` and
    ``MARKOV_HI_TOTAL_FAILS`` (entropy_source.rdl:831, :851) stay 0.
  * With whitening on, 16 input words give 8 digest words
    (architecture.adoc:142; entropy_source.adoc:104).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. SW_RESET_N baseline 0x20: only the TRNG domain runs. The
pattern noise driver (``env/sep_esrc_pattern_noise.py``) runs from before the
first TRNG reset release to the end of the leaf. Every start is a TRNG reset,
the eight defined ``INTR_ENABLE`` bits set, and the clean start
(``seq_lib/sep_esrc_clean_start_seq.py``) with ``ALERT_THRESHOLD`` = 0 and
``HEALTH_TEST_CTRL.ENABLE`` = 7. The second pattern trial, the last limit trial
and the all-off leg start with ``ALERT_THRESHOLD`` at its field maximum, so a
failing window counts towards the alert and the alert does not fire. Every window that a check uses runs the
lane-byte control. A window is W strobes of ``esrc_decor_valid_o``.

Randomization (``SepSeededRng`` from the run seed, drawn before any stimulus):
the lanes of the bias70 and bias30 trials (two different lanes), their windows
(two different windows of 1024, 2048 and 4096), the order of the two pattern
trials, the order of the three limit trials, the half-period L of the square
lanes, the balanced masks and permutation, the bias one positions, the square
phases and the alternate start values; then the window (1024 or 2048) and the
drawn ``HEALTH_TEST_CTRL.ENABLE`` value (1 to 4) of the all-off leg, the
``MIN_ENTROPY_H`` code H (0x02 to the field maximum) of the copy leg, and the
order in which that leg tries the other codes for H'.

Checkers:
  CHK-HT-TRIP      after 3W words of a bias pattern on lane k, of the bits
                   {0,3,4,5} of GENERATOR_k_HEALTH_STATUS exactly bit 3 is set.
  CHK-HT-PASS      bits 0, 4 and 5 of GENERATOR_k_HEALTH_STATUS read 0 in the
                   same trial (clean limits).
  CHK-HT-OTHERS    the other 11 generator statuses read 0 in the same trial.
  CHK-HT-ENABLE    with ENABLE bit 1 clear the same bias trial latches no bit 3
                   (control CTRL-HT-ENABLE-APT-CFG: the trip limit and ENABLE = 5
                   read back before the pattern starts);
                   with ENABLE bit 0 cleared while REPETITION_TEST_COUNT reads
                   at least 100, the count reads below 100 and below its value
                   before the write after one window (the run state is cleared).
                   The exact cleared value is not stated: OBS-HT-REPCOUNT-AFTER
                   logs it.
  CHK-HT-W1C       a write of 1 to the set bits of GENERATOR_k_HEALTH_STATUS
                   clears them. The write runs with every tester disabled, so no
                   window end can latch a bit between the write and the read;
                   control: the bits survive the tester disable.
  CHK-HT-PRESHA    with stuck0 on all lanes and whitening on, 16 whitener input
                   words give 8 digest words, exact: over the span between the
                   first and the last quiet clock of a trace of at least 64 input
                   words (env/sep_esrc_sha_tap.py), 2 x output words ==
                   INPUT_COUNT(first) + input words - INPUT_COUNT(last). Input words
                   are strobes of esrc_whiten_push_o, output words strobes of
                   esrc_compress_vld_o. Control: at least 16 input and 8 output
                   words in the span. Whether the whitener input continues after
                   the 32-bit test fails after boot is not stated: a push timeout
                   logs INFO-BLOCKED and the check has no evidence.
  CHK-HT-LIMIT     each limit trial (repetition L-3, Markov high W/2-3, Markov
                   low W/L+3, W = 1024) sets exactly the bit of its tester in all
                   12 generators.
  CHK-HT-TOP-ZERO  constant zero: HEALTH_TEST_STATUS bits 3 and 5, non-zero
                   APT_LO and MARKOV_LO totals, INTR_STATUS.HEALTH_TEST_FAILED.
  CHK-HT-TOP-HI    the same constant-zero windows: HEALTH_TEST_STATUS bit 4 reads 0,
                   APT_HI_TOTAL_FAILS and MARKOV_HI_TOTAL_FAILS read 0. Controls:
                   every total reads 0 at the start (CTRL-HT-TOP-ZERO); the same
                   windows trip the APT and Markov low side of the same tester
                   (CHK-HT-TOP-ZERO); the ones leg of the same shard makes
                   APT_HI_TOTAL_FAILS non-zero (CHK-HT-TOP-ONE); the Markov high
                   limit trial (shard 2) sets bit 4 in all 12 generators
                   (CHK-HT-LIMIT tester=mkv_hi).
  CHK-HT-TOP-ONE   constant ones, compressor in use, whitening off,
                   APT_PROPORTION_LO = 0: HEALTH_TEST_STATUS bit 3 (the 32-bit
                   tester, high side only) and a non-zero APT_HI_TOTAL_FAILS (any
                   instance); controls: APT_PROPORTION_LO reads back 0,
                   APT_LO_TOTAL_FAILS does not change over the ones windows, and
                   APT_HI_TOTAL_FAILS reads 0 after the constant-zero leg.
  CHK-HT-ALL-OFF   ENABLE = 0 (entropy_source.rdl:314) and stuck1 on all lanes
                   for 2W words, with MARKOV PROB_10_THRESHOLD = 1 and
                   ALERT_THRESHOLD at its maximum: every GENERATOR_k_HEALTH_STATUS
                   reads 0 and ALERT_SUMMARY_FAIL_COUNTS.ANY_FAIL_COUNT reads 0.
                   Control (CTRL-HT-ALL-OFF): the same pattern with ENABLE = 7 for
                   2W more words latches bits 0, 3 and 5 in every generator and
                   makes ANY_FAIL_COUNT non-zero.
  CHK-HT-ENABLE    (tester=set) after the all-off control, the drawn ENABLE value
                   with the same pattern for 2W words latches in every generator
                   exactly the bits of the enabled testers: bit 0 for ENABLE bit
                   0, bit 3 for bit 1, bit 5 for bit 2.
  CHK-REC-COPY     window 1024 (APT_LIMIT is derived for a 1024-sample window,
                   entropy_source.rdl:971), APT_PROPORTION_LO = 0, every tester
                   off outside a trial: MIN_ENTROPY_H = H, RECOMMENDED_THRESHOLDS
                   RCT_LIMIT C and APT_LIMIT A copied into REPETITION_LIMIT and
                   APT_PROPORTION_1BIT read back exactly (part copy); writes of
                   MIN_ENTROPY_H alone, up to the first code H' whose RCT_LIMIT
                   C' differs from C, leave both limits unchanged (part h_only);
                   with H' written and only the repetition tester on, runs of C
                   words on all lanes latch nothing and runs of C + 1 latch
                   exactly bit 0 in every generator ("Maximum allowed",
                   entropy_source.rdl:320); with only the APT tester on, a
                   1024-word period with A ones latches nothing and one with
                   A + 1 latches exactly bit 3 (entropy_source.rdl:394); C'
                   copied into REPETITION_LIMIT flips the result of the run
                   length between C and C' (C + 1 when C' > C, C when C' < C).
                   Controls (CTRL-REC-COPY): the H readbacks, A + 1 within the
                   window, the cleared statuses and the ENABLE readback before
                   each trial.
Logged only: OBS-ESRC-HT-TOTALS, the five total-fail counters after each limit
trial (no text states how the totals count the per-generator failures).
OBS-HT-ALERT-COUNTS, the ALERT_FAIL_COUNTS fields and ALERT_THRESHOLD after each
pattern trial and each limit trial, each of which fails one tester type (no text
states which tester instances feed those counters).
OBS-ESRC-HT-BYPASS, HEALTH_TEST_STATUS bits 3 and 5 and the APT_LO and MARKOV_LO
totals after the constant-zero windows with ``CTRL.BYPASS_ENTROPY_COMPRESSOR``
set: architecture.adoc:47-48 states the 32-bit test clock-gated off in that mode,
architecture.adoc:122 states that it monitors the post-bypass stream. Control
CTRL-ESRC-HT-BYPASS: CTRL reads the bypass 1 before the windows, and the
lane-byte control compares at least W zero strobes with no mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_esrc_pattern_noise import (
    BIAS30_ONES,
    BIAS70_ONES,
    NUM_LANES,
    Alternate,
    Balanced,
    EsrcStrobeTimeout,
    LanePattern,
    Ones,
    SepEsrcPatternNoise,
    Square,
    Stuck,
    alternate_lane,
    balanced_lanes,
    bias_lane,
    describe,
    square_lane,
)
from env.sep_esrc_sha_tap import BLOCK_WORDS, DIGEST_WORDS, SepEsrcShaTap
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_open_value_leg_pass,
)
from env.sep_seeded_rng import SepSeededRng
from env.sep_shard import sep_shard
from env.sep_trial_wait import TrialTimeout
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, sym
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_clean_start_seq import SepEsrcCleanStart, SepEsrcLeafSetup

TEST = "sep_esrc_health_pattern_rand_test"

BASELINE_PARK = ("otbn", "aes", "hmac", "kmac", "abr")
WINDOWS = (1024, 2048, 4096)
LIMIT_WINDOW = 1024
RESET_WINDOW = 2048
LIMIT_TRIALS = ("rep", "mkv_hi", "mkv_lo")
SQUARE_LS = (8, 16, 32)
OFF_WINDOWS = (1024, 2048)
DRAWN_ENABLES = (1, 2, 3, 4)
# HEALTH_TEST_CTRL.ENABLE bits 0, 1 and 2: repetition, APT, Markov (entropy_source.rdl:314).
HT_EN_REP, HT_EN_APT, HT_EN_MKV = 1, 2, 4
# Any minimum alternation count above 0 fails a stuck lane, which has none.
MKV_LO_TRIP = 1
SWITCH_WORDS = 4  # words of a pattern change with every tester off

REPCOUNT_PRE = 100  # REPETITION_TEST_COUNT value that shows a live run
REPCOUNT_PRE_WORDS = 128 + REPCOUNT_PRE
PRESHA_PUSHES = 64
PRESHA_TAIL = 4  # input words past PRESHA_PUSHES, so the trace ends after a quiet clock
DRAIN_POPS = 160

# Shards (env/sep_shard.py). Every group starts with its own TRNG reset.
# 1: both pattern trials and the APT enable leg, which repeats the first trial.
# 2: the repetition enable leg and the limit trials, which its grade reads, then
#    the all-off leg and the threshold copy leg.
# 3: the constant-zero, constant-ones and bypass-zero legs; the ones leg reads the zero leg.
SHARD_EVIDENCE = {
    1: ("CHK-HT-TRIP", "CHK-HT-PASS", "CHK-HT-OTHERS", "CHK-HT-W1C", "CHK-HT-ENABLE"),
    2: ("CHK-HT-ENABLE", "CHK-HT-LIMIT", "CHK-HT-ALL-OFF", "CHK-REC-COPY"),
    3: ("CHK-HT-PRESHA", "CHK-HT-TOP-ZERO", "CHK-HT-TOP-HI", "CHK-HT-TOP-ONE"),
}


def _addr(reg: str) -> int:
    return sym(f"ENTROPY_SOURCE_{reg}_REG_ADDR")


def _fbm(reg: str, field: str) -> int:
    return ENTROPY_SOURCE.fields(reg)[field]["bm"]


def _fbp(reg: str, field: str) -> int:
    return ENTROPY_SOURCE.fields(reg)[field]["bp"]


def _timeout_reason(exc: TrialTimeout | EsrcStrobeTimeout) -> str:
    return f"timeout:{exc.what}" if isinstance(exc, TrialTimeout) else "timeout:strobes"


def _freset(reg: str, field: str) -> int:
    return ENTROPY_SOURCE.fields(reg)[field]["reset"]


A_CTRL = _addr("CTRL")
A_INTR_STATUS = _addr("INTR_STATUS")
A_INTR_ENABLE = _addr("INTR_ENABLE")
A_FIFO_STATUS = _addr("FIFO_STATUS")
A_FIFO_RDATA = _addr("FIFO_RDATA")
A_HT_CTRL = _addr("HEALTH_TEST_CTRL")
A_HT_STATUS = _addr("HEALTH_TEST_STATUS")
A_REP_COUNT = _addr("REPETITION_TEST_COUNT")
A_APT_1BIT = _addr("APT_PROPORTION_1BIT")
A_APT_LO = _addr("APT_PROPORTION_LO")
A_MARKOV = _addr("MARKOV_TEST_PROB_THRESHOLDS")
A_ALERT_THRESHOLD = _addr("ALERT_THRESHOLD")
A_MIN_H = _addr("MIN_ENTROPY_H")
A_REC = _addr("RECOMMENDED_THRESHOLDS")
A_ALERT_FAIL_COUNTS = _addr("ALERT_FAIL_COUNTS")
A_ANY_FAIL = _addr("ALERT_SUMMARY_FAIL_COUNTS")
A_GEN_STATUS = tuple(_addr(f"GENERATOR_{n}_HEALTH_STATUS") for n in range(NUM_LANES))
TOTALS = (
    "REPCNT_TOTAL_FAILS",
    "APT_HI_TOTAL_FAILS",
    "APT_LO_TOTAL_FAILS",
    "MARKOV_HI_TOTAL_FAILS",
    "MARKOV_LO_TOTAL_FAILS",
)
A_TOTALS = {name: _addr(name) for name in TOTALS}

INTR_ENABLE_ALL = ENTROPY_SOURCE.mask("INTR_ENABLE")
M_HT_FAILED = _fbm("INTR_STATUS", "HEALTH_TEST_FAILED")
M_FIFO_LEVEL = _fbm("FIFO_STATUS", "LEVEL")
M_REP_COUNT = _fbm("REPETITION_TEST_COUNT", "REPETITION_COUNT")
M_GEN = ENTROPY_SOURCE.mask("GENERATOR_0_HEALTH_STATUS")
M_HT_STATUS = ENTROPY_SOURCE.mask("HEALTH_TEST_STATUS")
M_APT_LO = _fbm("APT_PROPORTION_LO", "LIMIT")
M_TOTAL = _fbm("REPCNT_TOTAL_FAILS", "FAIL_COUNT")
M_HT_ENABLE = _fbm("HEALTH_TEST_CTRL", "ENABLE")
P_HT_ENABLE = _fbp("HEALTH_TEST_CTRL", "ENABLE")
M_REP_LIMIT = _fbm("HEALTH_TEST_CTRL", "REPETITION_LIMIT")
P_REP_LIMIT = _fbp("HEALTH_TEST_CTRL", "REPETITION_LIMIT")
M_APT_1BIT = _fbm("APT_PROPORTION_1BIT", "LIMIT")
P_APT_1BIT = _fbp("APT_PROPORTION_1BIT", "LIMIT")
M_MIN_H = _fbm("MIN_ENTROPY_H", "H")
P_MIN_H = _fbp("MIN_ENTROPY_H", "H")
H_MAX = M_MIN_H >> P_MIN_H
# RCT_LIMIT is 1 + ceil(20 / H) in 16 bits (entropy_source.rdl:966-967), and
# REPETITION_LIMIT holds 8 bits (:322): code 0x01 gives 321, code 0x02 gives 161.
REC_H_MIN = 0x02
M_RCT = _fbm("RECOMMENDED_THRESHOLDS", "RCT_LIMIT")
P_RCT = _fbp("RECOMMENDED_THRESHOLDS", "RCT_LIMIT")
M_APT_REC = _fbm("RECOMMENDED_THRESHOLDS", "APT_LIMIT")
P_APT_REC = _fbp("RECOMMENDED_THRESHOLDS", "APT_LIMIT")
M_THR = _fbm("ALERT_THRESHOLD", "THRESHOLD")
P_THR = _fbp("ALERT_THRESHOLD", "THRESHOLD")
ALERT_THR_MAX = M_THR >> P_THR
M_ANY_FAIL = _fbm("ALERT_SUMMARY_FAIL_COUNTS", "ANY_FAIL_COUNT")
P_ANY_FAIL = _fbp("ALERT_SUMMARY_FAIL_COUNTS", "ANY_FAIL_COUNT")
ALERT_FAIL_FIELDS = ENTROPY_SOURCE.fields("ALERT_FAIL_COUNTS")

M_CTRL_BYPASS = _fbm("CTRL", "BYPASS_ENTROPY_COMPRESSOR")
P_CTRL_BYPASS = _fbp("CTRL", "BYPASS_ENTROPY_COMPRESSOR")
# Clocks the leaf holds an FCOV leg pass label before it writes 0.
LEG_LABEL_CLKS = 2

# Status bit allocation (architecture.adoc:126).
BIT_REP, BIT_APT, BIT_MKV_HI, BIT_MKV_LO = 0, 3, 4, 5
GRADED_BITS = (1 << BIT_REP) | (1 << BIT_APT) | (1 << BIT_MKV_HI) | (1 << BIT_MKV_LO)
TRIP_BIT = {"rep": BIT_REP, "mkv_hi": BIT_MKV_HI, "mkv_lo": BIT_MKV_LO}
# The generator status bit of each ENABLE bit; Markov is the low side under stuck1.
ENABLE_BITS = ((HT_EN_REP, BIT_REP), (HT_EN_APT, BIT_APT), (HT_EN_MKV, BIT_MKV_LO))


def enabled_bits(enable: int) -> int:
    """Generator status bits that stuck1 latches with ``enable``."""
    return sum(1 << bit for en, bit in ENABLE_BITS if enable & en)


@dataclass(frozen=True)
class Spread(LanePattern):
    """``ones`` ones in every ``period`` words at evenly spread positions, so every
    run of ``period`` consecutive words holds exactly ``ones`` ones."""

    ones: int
    period: int

    def bit(self, n: int) -> int:
        i = n % self.period
        return (i + 1) * self.ones // self.period - i * self.ones // self.period

    def describe(self) -> str:
        return f"spread({self.ones}/{self.period})"


# Reset limits of the window 2048 (the RDL reset column).
RESET_APT_1BIT = _freset("APT_PROPORTION_1BIT", "LIMIT")
RESET_REP_LIMIT = _freset("HEALTH_TEST_CTRL", "REPETITION_LIMIT")


@dataclass(frozen=True)
class PatternTrial:
    name: str  # bias70 or bias30
    lane: int
    window: int
    pattern: Ones

    @property
    def tester(self) -> str:
        return "apt_hi" if self.name == "bias70" else "apt_lo"

    @property
    def limit(self) -> int:
        # bias70: 45W/64 ones against 19W/32; bias30: 19W/64 ones against 13W/32.
        return 19 * self.window // 32 if self.name == "bias70" else 13 * self.window // 32

    @property
    def stat(self) -> int:
        ones = BIAS70_ONES if self.name == "bias70" else BIAS30_ONES
        return ones * self.window // 64


@dataclass(frozen=True)
class Plan:
    seed: int
    balanced: tuple[Balanced, ...]
    trials: tuple[PatternTrial, ...]  # drawn order
    limit_order: tuple[str, ...]
    half_period: int
    squares: tuple[Square, ...]
    alternates: tuple[Alternate, ...]
    off_window: int
    enable_drawn: int
    rec_h: int
    rec_h_order: tuple[int, ...]

    def describe(self) -> str:
        tr = " ".join(
            f"{t.name}:lane={t.lane},window={t.window},limit={t.limit},"
            f"ones={sorted(t.pattern.positions)}"
            for t in self.trials
        )
        return (
            f"trials=[{tr}] limit_order={','.join(self.limit_order)} L={self.half_period} "
            f"squares=[{','.join(s.describe() for s in self.squares)}] "
            f"alternates=[{','.join(a.describe() for a in self.alternates)}] "
            f"off_window={self.off_window} enable_drawn={self.enable_drawn} "
            f"rec_h=0x{self.rec_h:02x} {describe(self.balanced)}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    balanced = tuple(balanced_lanes(rng))
    lanes = rng.sample(range(NUM_LANES), 2)
    windows = rng.sample(WINDOWS, 2)
    b70 = PatternTrial("bias70", lanes[0], windows[0], bias_lane(rng, BIAS70_ONES))
    b30 = PatternTrial("bias30", lanes[1], windows[1], bias_lane(rng, BIAS30_ONES))
    trials = [b70, b30]
    rng.shuffle(trials)
    limit_order = list(LIMIT_TRIALS)
    rng.shuffle(limit_order)
    half_period = rng.choice(SQUARE_LS)
    squares = tuple(square_lane(rng, half_period) for _ in range(NUM_LANES))
    alternates = tuple(alternate_lane(rng) for _ in range(NUM_LANES))
    off_window = rng.choice(OFF_WINDOWS)
    enable_drawn = rng.choice(DRAWN_ENABLES)
    rec_h = rng.randrange(REC_H_MIN, H_MAX + 1)
    rec_h_order = [h for h in range(REC_H_MIN, H_MAX + 1) if h != rec_h]
    rng.shuffle(rec_h_order)
    return Plan(
        seed,
        balanced,
        tuple(trials),
        tuple(limit_order),
        half_period,
        squares,
        alternates,
        off_window,
        enable_drawn,
        rec_h,
        tuple(rec_h_order),
    )


class _Esrc(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


@pyuvm.test()
class sep_esrc_health_pattern_rand_test(sep_base_test):
    """Per-lane APT trips, shared limits, enables, W1C, limit trips and the 32-bit tester."""

    required_evidence = (
        "CHK-HT-TRIP",
        "CHK-HT-PASS",
        "CHK-HT-OTHERS",
        "CHK-HT-ENABLE",
        "CHK-HT-W1C",
        "CHK-HT-PRESHA",
        "CHK-HT-LIMIT",
        "CHK-HT-TOP-ZERO",
        "CHK-HT-TOP-HI",
        "CHK-HT-TOP-ONE",
        "CHK-HT-ALL-OFF",
        "CHK-REC-COPY",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        shard = sep_shard(self, SHARD_EVIDENCE)
        await self.bring_up_no_cpu(park=BASELINE_PARK)
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.esrc = _Esrc(self)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        # The testers run from the TRNG reset release, so balanced noise runs before it.
        self.noise.start(plan.balanced)
        self.p: int | None = None
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)

        # The first start is bring-up (SepEsrcLeafSetup raises). A later set-up or
        # strobe wait that times out fails the check of its trial (reason=timeout) and
        # the leaf goes on with the next trial, which starts with its own TRNG reset.
        def runs(group: int) -> bool:
            return shard is None or shard == group

        trip_results: dict[str, bool] = {}
        if runs(1):
            for i, trial in enumerate(plan.trials):
                trip_results[trial.name] = await self._guard(
                    self._pattern_trial(trial, thr=ALERT_THR_MAX if i else 0),
                    ("HT-TRIP",),
                    False,
                    pattern=trial.name,
                    lane=trial.lane,
                )
            await self._guard(
                self._apt_enable_leg(plan.trials[0], trip_results[plan.trials[0].name]),
                ("HT-ENABLE",),
                None,
                tester="apt",
            )
        if runs(2):
            self.rep_timeout = ""
            rep_before, rep_after = await self._guard(
                self._rep_enable_leg(), (), (None, None), tester="rep"
            )
            limit_status = await self._limit_trials()
            self._grade_rep_enable(rep_before, rep_after, limit_status)
            await self._guard(self._all_off_leg(), ("HT-ALL-OFF", "HT-ENABLE"), None)
            await self._guard(self._rec_copy_leg(), ("REC-COPY",), None)
        if runs(3):
            apt_hi_zero = await self._guard(self._zero_leg(), ("HT-TOP-ZERO", "HT-TOP-HI"), None)
            await self._guard(self._ones_leg(apt_hi_zero), ("HT-TOP-ONE",), None)
            await self._bypass_zero_leg()
        close_graded_window(self.logger)

        await self.noise.stop()
        await self.clk.stop()
        self.chk.finish()

    async def _guard(self, coro, checks: tuple[str, ...], default, **fields):
        """Run one trial; a set-up or strobe timeout fails ``checks`` with the reason."""
        try:
            return await coro
        except (TrialTimeout, EsrcStrobeTimeout) as exc:
            close_graded_window(self.logger)
            self.noise.byte_check(False)
            reason = _timeout_reason(exc)
            for name in checks:
                self.chk.ok(name, False, reason=reason, bound=exc.bound, **fields)
            if not checks:
                self.rep_timeout = reason
            return default

    # --- bus helpers -----------------------------------------------------------
    async def _rd(self, addr: int) -> int:
        return await self.esrc._rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.esrc._wr(addr, data)

    def _now(self) -> int:
        return self.clk.clk

    async def _ht_ctrl(self, *, enable: int | None = None, rep_limit: int | None = None) -> None:
        """Read-modify-write of HEALTH_TEST_CTRL on its field bits."""
        v = await self._rd(A_HT_CTRL)
        if enable is not None:
            v = (v & ~M_HT_ENABLE) | ((enable << P_HT_ENABLE) & M_HT_ENABLE)
        if rep_limit is not None:
            v = (v & ~M_REP_LIMIT) | ((rep_limit << P_REP_LIMIT) & M_REP_LIMIT)
        await self._wr(A_HT_CTRL, v & ENTROPY_SOURCE.mask("HEALTH_TEST_CTRL"))

    async def _gen_statuses(self) -> list[int]:
        return [(await self._rd(a)) & M_GEN for a in A_GEN_STATUS]

    async def _clear_gen_statuses(self) -> None:
        for addr, s in zip(A_GEN_STATUS, await self._gen_statuses()):
            if s:
                await self._wr(addr, s)

    async def _any_fail(self) -> int:
        return ((await self._rd(A_ANY_FAIL)) & M_ANY_FAIL) >> P_ANY_FAIL

    async def _alert_counts_obs(self, tester: str) -> None:
        """OBS-HT-ALERT-COUNTS after a trial that fails only ``tester``."""
        raw = await self._rd(A_ALERT_FAIL_COUNTS)
        thr = ((await self._rd(A_ALERT_THRESHOLD)) & M_THR) >> P_THR
        counts = {f.lower(): (raw & m["bm"]) >> m["bp"] for f, m in ALERT_FAIL_FIELDS.items()}
        self.chk.obs("HT-ALERT-COUNTS", tester=tester, alert_threshold=thr, **counts)

    async def _drain(self) -> None:
        """Pop FIFO_RDATA until FIFO_STATUS.LEVEL reads 0."""
        for _ in range(DRAIN_POPS):
            if (await self._rd(A_FIFO_STATUS)) & M_FIFO_LEVEL == 0:
                return
            await self._rd(A_FIFO_RDATA)
        raise AssertionError(f"ESRC FIFO_STATUS.LEVEL not 0 after {DRAIN_POPS} pops")

    async def _write_reset_limits(self) -> None:
        await self._wr(A_APT_1BIT, ENTROPY_SOURCE.value("APT_PROPORTION_1BIT"))
        await self._wr(A_APT_LO, ENTROPY_SOURCE.value("APT_PROPORTION_LO"))
        await self._wr(A_MARKOV, ENTROPY_SOURCE.value("MARKOV_TEST_PROB_THRESHOLDS"))
        await self._ht_ctrl(rep_limit=RESET_REP_LIMIT)

    # --- word-counted waits ----------------------------------------------------
    def _word_bound(self, count: int, window: int) -> int:
        """Clock bound of a wait for ``count`` strobes: the count plus one window."""
        return (count + window) * (self.p or 64)

    async def _wait_words(self, count: int, window: int) -> None:
        await self.noise.wait_words(count, self._word_bound(count, window))

    async def _pattern_window(self, patterns: list[LanePattern], words: int, window: int) -> None:
        """Apply ``patterns`` at the next strobe, count ``words`` whole words with the
        lane-byte control on, and log the control."""
        c0, m0 = self.noise.byte_control()
        self.noise.byte_check(True)
        self.noise.set_lanes(patterns)
        # The change lands at the next strobe; the words after it are whole.
        await self._wait_words(words + 1, window)
        self.noise.byte_check(False)
        c1, m1 = self.noise.byte_control()
        self.chk.ctrl("NOISE-BYTES", m1 == m0 and c1 > c0, compared=c1 - c0, mismatched=m1 - m0)

    # --- start sequence ----------------------------------------------------------
    async def _trng_reset(self) -> int:
        return await self.setup.trng_reset()

    async def _start(
        self, window: int, ctrl_fields: dict[str, int] | None = None, thr: int = 0
    ) -> None:
        """Reset sequence, INTR_ENABLE, clean start(W), BOOT_PHASE_DONE, statuses 0."""
        close_graded_window(self.logger)
        mark = await self._trng_reset()
        await self._wr(A_INTR_ENABLE, INTR_ENABLE_ALL)
        cs = SepEsrcCleanStart(
            self,
            self.noise,
            self.plan.balanced,
            window=window,
            ctrl_fields=ctrl_fields,
            health_enable=7,
            extra_writes=(
                (A_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=thr)),
            ),
        )
        await cs.run(release_mark=mark)
        self.p = await self.setup.measure_period(self.chk)
        await self.setup.wait_boot_done(self.esrc, window)
        st = await self._gen_statuses()
        self.chk.ctrl(
            "HT-START-ZERO",
            all(s == 0 for s in st),
            window=window,
            gen_status=[f"0x{s:02x}" for s in st],
        )

    def _lanes_with(self, lane: int, pattern: LanePattern) -> list[LanePattern]:
        lanes: list[LanePattern] = list(self.plan.balanced)
        lanes[lane] = pattern
        return lanes

    async def _write_trip_limit(self, trial: PatternTrial) -> None:
        if trial.name == "bias70":
            await self._wr(
                A_APT_1BIT, ENTROPY_SOURCE.value("APT_PROPORTION_1BIT", LIMIT=trial.limit)
            )
        else:
            await self._wr(A_APT_LO, ENTROPY_SOURCE.value("APT_PROPORTION_LO", LIMIT=trial.limit))

    # --- pattern trials -----------------------------------------------------------
    async def _pattern_trial(self, trial: PatternTrial, thr: int) -> bool:
        """One bias trial; returns True when lane k latched bit 3."""
        w, k = trial.window, trial.lane
        await self._start(w, thr=thr)
        open_graded_window(TEST, self.logger)
        await self._write_trip_limit(trial)
        await self._pattern_window(self._lanes_with(k, trial.pattern), 3 * w, w)
        st = await self._gen_statuses()
        await self._alert_counts_obs(trial.tester)
        gk = st[k]
        tripped = gk & GRADED_BITS == 1 << BIT_APT
        self.chk.ok(
            "HT-TRIP",
            tripped,
            pattern=trial.name,
            lane=k,
            window=w,
            tester=trial.tester,
            limit=trial.limit,
            stat=trial.stat,
            gen_status=f"0x{gk:02x}",
        )
        side = gk & ((1 << BIT_REP) | (1 << BIT_MKV_HI) | (1 << BIT_MKV_LO))
        self.chk.ok(
            "HT-PASS",
            side == 0,
            pattern=trial.name,
            lane=k,
            rep_bit=(gk >> BIT_REP) & 1,
            mkv_hi_bit=(gk >> BIT_MKV_HI) & 1,
            mkv_lo_bit=(gk >> BIT_MKV_LO) & 1,
            limits="clean",
            windows=3,
            ctrl_trip=int(bool(gk & (1 << BIT_APT))),
        )
        others = [s for j, s in enumerate(st) if j != k]
        others_flags = sum(1 << j for j, s in enumerate(st) if j != k and s)
        self.chk.ctrl("HT-OTHERS", bool(gk & (1 << BIT_APT)), lane=k, gen_status=f"0x{gk:02x}")
        self.chk.ok(
            "HT-OTHERS",
            all(s == 0 for s in others),
            pattern=trial.name,
            lane=k,
            other_generators_status=f"0x{others_flags:03x}",
            other_ones=w // 2,
            limit=trial.limit,
            ctrl_lane_latched=int(bool(gk & (1 << BIT_APT))),
        )
        # W1C under disabled testers: no window end can latch a bit between the
        # write and the read. The FCOV window is closed: the stored ENABLE = 0 bin
        # belongs to CHK-HT-ALL-OFF.
        close_graded_window(self.logger)
        before = (await self._rd(A_GEN_STATUS[k])) & M_GEN
        await self._ht_ctrl(enable=0)
        hold = (await self._rd(A_GEN_STATUS[k])) & M_GEN
        self.chk.ctrl(
            "HT-W1C-HOLD",
            hold == before and bool(before & (1 << BIT_APT)),
            before=f"0x{before:02x}",
            after_disable=f"0x{hold:02x}",
        )
        await self._wr(A_GEN_STATUS[k], hold)
        after_raw = await self._rd(A_GEN_STATUS[k])
        after = after_raw & M_GEN
        self.chk.ok(
            "HT-W1C",
            bool(before & (1 << BIT_APT)) and after == 0,
            lane=k,
            before=f"0x{before:02x}",
            after=f"0x{after:02x}",
            rsvd=f"0x{after_raw & ~M_GEN & 0xFFFFFFFF:x}",
        )
        await self._ht_ctrl(enable=7)
        return bool(gk & (1 << BIT_APT))

    async def _apt_enable_leg(self, trial: PatternTrial, ctrl_tripped: bool) -> None:
        """The first trial again with HEALTH_TEST_CTRL.ENABLE = 5 (APT disabled)."""
        w, k = trial.window, trial.lane
        await self._start(w)
        open_graded_window(TEST, self.logger)
        await self._ht_ctrl(enable=5)
        await self._write_trip_limit(trial)
        reg = "APT_PROPORTION_1BIT" if trial.name == "bias70" else "APT_PROPORTION_LO"
        a_lim = A_APT_1BIT if trial.name == "bias70" else A_APT_LO
        lim = (await self._rd(a_lim) & _fbm(reg, "LIMIT")) >> _fbp(reg, "LIMIT")
        enable = (await self._rd(A_HT_CTRL) & M_HT_ENABLE) >> P_HT_ENABLE
        self.chk.ctrl(
            "HT-ENABLE-APT-CFG",
            lim == trial.limit and enable == 5,
            reg=reg,
            limit=lim,
            want_limit=trial.limit,
            enable=enable,
            want_enable=5,
        )
        await self._pattern_window(self._lanes_with(k, trial.pattern), 3 * w, w)
        gk = (await self._rd(A_GEN_STATUS[k])) & M_GEN
        close_graded_window(self.logger)
        self.chk.ctrl("HT-ENABLE-APT", ctrl_tripped, pattern=trial.name, ctrl_enabled_trips=1)
        self.chk.ok(
            "HT-ENABLE",
            (gk >> BIT_APT) & 1 == 0,
            tester="apt",
            pattern=trial.name,
            lane=k,
            enable_bit=0,
            latched=(gk >> BIT_APT) & 1,
            count_before="na",
            count_after_disable="na",
            gen_status=f"0x{gk:02x}",
            ctrl_enabled_trips=int(ctrl_tripped),
        )

    # --- repetition enable leg ------------------------------------------------------
    async def _rep_enable_leg(self) -> tuple[int | None, int | None]:
        """Stuck1 on all lanes, REPETITION_TEST_COUNT >= 100, then ENABLE = 6."""
        w = RESET_WINDOW
        await self._start(w)
        open_graded_window(TEST, self.logger)
        self.noise.set_lanes([Stuck(1)] * NUM_LANES)
        bound = self._word_bound(REPCOUNT_PRE_WORDS, 0)
        t0 = self._now()
        before: int | None = None
        last = 0
        while self._now() - t0 <= bound:
            last = (await self._rd(A_REP_COUNT)) & M_REP_COUNT
            if last >= REPCOUNT_PRE:
                before = last
                break
        self.chk.ctrl(
            "HT-REPCOUNT-PRE",
            before is not None,
            count=last,
            want_ge=REPCOUNT_PRE,
            bound=bound,
        )
        if before is None:
            close_graded_window(self.logger)
            return None, None
        await self._ht_ctrl(enable=6)
        await self._wait_words(w, w)
        after = (await self._rd(A_REP_COUNT)) & M_REP_COUNT
        close_graded_window(self.logger)
        self.chk.obs("HT-REPCOUNT-AFTER", value=after, before=before)
        self.chk.blocked("HT-ENABLE-REPCOUNT-VALUE", "cleared_count_value_unstated")
        return before, after

    def _grade_rep_enable(
        self, before: int | None, after: int | None, limit_status: dict[str, list[int]]
    ) -> None:
        rep_st = limit_status.get("rep", [])
        rep_trips = bool(rep_st) and all((s >> BIT_REP) & 1 for s in rep_st)
        self.chk.ctrl("HT-ENABLE-REP", rep_trips, ctrl_enabled_trips=int(rep_trips))
        ok = before is not None and after is not None and after < REPCOUNT_PRE and after < before
        extra = {"reason": self.rep_timeout} if self.rep_timeout else {}
        self.chk.ok(
            "HT-ENABLE",
            ok,
            **extra,
            tester="rep",
            enable_bit=0,
            latched="na",
            count_before=before if before is not None else "na",
            count_after_disable=after if after is not None else "na",
            ctrl_enabled_trips=int(rep_trips),
        )

    # --- limit trials -----------------------------------------------------------------
    def _limit_patterns(self, trial: str) -> list[LanePattern]:
        if trial == "mkv_hi":
            return list(self.plan.alternates)
        return list(self.plan.squares)

    def _limit_value(self, trial: str) -> int:
        w, half = LIMIT_WINDOW, self.plan.half_period
        return {"rep": half - 3, "mkv_hi": w // 2 - 3, "mkv_lo": w // half + 3}[trial]

    async def _write_limit(self, trial: str) -> None:
        lim = self._limit_value(trial)
        w = LIMIT_WINDOW
        if trial == "rep":
            await self._ht_ctrl(rep_limit=lim)
        elif trial == "mkv_hi":
            await self._wr(
                A_MARKOV,
                ENTROPY_SOURCE.value(
                    "MARKOV_TEST_PROB_THRESHOLDS", PROB_01_THRESHOLD=lim, PROB_10_THRESHOLD=0
                ),
            )
        else:
            await self._wr(
                A_MARKOV,
                ENTROPY_SOURCE.value(
                    "MARKOV_TEST_PROB_THRESHOLDS", PROB_01_THRESHOLD=w + 1, PROB_10_THRESHOLD=lim
                ),
            )

    async def _limit_trials(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        words: dict[str, int] = {}
        reasons: dict[str, str] = {}
        for trial in self.plan.limit_order:
            try:
                thr = ALERT_THR_MAX if trial == self.plan.limit_order[-1] else 0
                await self._limit_trial(trial, out, words, thr)
            except (TrialTimeout, EsrcStrobeTimeout) as exc:
                close_graded_window(self.logger)
                self.noise.byte_check(False)
                what = exc.what if isinstance(exc, TrialTimeout) else "strobes"
                reasons[trial] = f"timeout:{what} bound={exc.bound}"
                out[trial] = []
                words[trial] = 0
        return self._grade_limits(out, words, reasons)

    async def _limit_trial(self, trial: str, out: dict, words: dict, thr: int) -> None:
        """One limit trial: a pattern below the limit at clean limits, then the limit."""
        w = LIMIT_WINDOW
        await self._start(w, thr=thr)
        await self._pattern_window(self._limit_patterns(trial), 2 * w, w)
        pre = await self._gen_statuses()
        self.chk.ctrl(
            "HT-LIMIT",
            all(s == 0 for s in pre),
            tester=trial,
            clean_limits_status=[f"0x{s:02x}" for s in pre],
        )
        open_graded_window(TEST, self.logger)
        await self._write_limit(trial)
        c0, m0 = self.noise.byte_control()
        self.noise.byte_check(True)
        mark = self.noise.mark()
        await self._wait_words(2 * w, w)
        self.noise.byte_check(False)
        c1, m1 = self.noise.byte_control()
        self.chk.ctrl("NOISE-BYTES", m1 == m0 and c1 > c0, compared=c1 - c0, mismatched=m1 - m0)
        words[trial] = self.noise.words_since(mark)
        out[trial] = await self._gen_statuses()
        _, totals, _ = await self._top_regs()
        self.chk.obs("ESRC-HT-TOTALS", tester=trial, windows=2, **totals)
        await self._alert_counts_obs(trial)
        close_graded_window(self.logger)
        for addr, s in zip(A_GEN_STATUS, out[trial]):
            if s:
                await self._wr(addr, s)

    def _grade_limits(
        self, out: dict[str, list[int]], words: dict[str, int], reasons: dict[str, str]
    ) -> dict[str, list[int]]:
        w = LIMIT_WINDOW
        for trial in self.plan.limit_order:
            bit = TRIP_BIT[trial]
            st = out[trial]
            exact = all(s & GRADED_BITS == 1 << bit for s in st)
            others = [t for t in self.plan.limit_order if t != trial]
            ctrl_ok = all(((s >> bit) & 1) == 0 for t in others for s in out[t])
            self.chk.ctrl("HT-LIMIT-OTHER-TRIALS", ctrl_ok, tester=trial, bit=bit)
            pattern = "alternate" if trial == "mkv_hi" else f"square_{self.plan.half_period}"
            stray = 0
            for s in st:
                stray |= s & GRADED_BITS & ~(1 << bit)
            extra = {"reason": reasons[trial]} if trial in reasons else {}
            self.chk.ok(
                "HT-LIMIT",
                exact and bool(st),
                **extra,
                tester=trial,
                pattern=pattern,
                limit=self._limit_value(trial),
                window=w,
                words=words[trial],
                gen_status_all=[f"0x{s:02x}" for s in st],
                other_bits=f"0x{stray:02x}",
            )
        return out

    # --- all-off leg ------------------------------------------------------------------
    async def _all_off_leg(self) -> None:
        """CHK-HT-ALL-OFF, its ENABLE = 7 control, then CHK-HT-ENABLE for the drawn value."""
        w = self.plan.off_window
        stuck: list[LanePattern] = [Stuck(1)] * NUM_LANES
        await self._start(w, thr=ALERT_THR_MAX)
        open_graded_window(TEST, self.logger)
        await self._ht_ctrl(enable=0)
        await self._wr(
            A_MARKOV,
            ENTROPY_SOURCE.value(
                "MARKOV_TEST_PROB_THRESHOLDS",
                PROB_01_THRESHOLD=w + 1,
                PROB_10_THRESHOLD=MKV_LO_TRIP,
            ),
        )
        enable = ((await self._rd(A_HT_CTRL)) & M_HT_ENABLE) >> P_HT_ENABLE
        thr = ((await self._rd(A_ALERT_THRESHOLD)) & M_THR) >> P_THR
        await self._pattern_window(stuck, 2 * w, w)
        st = await self._gen_statuses()
        any_fail = await self._any_fail()
        top = (await self._rd(A_HT_STATUS)) & M_HT_STATUS
        self.chk.ctrl("HT-ALL-OFF", enable == 0 and thr == ALERT_THR_MAX, enable=enable, thr=thr)
        self.chk.ok(
            "HT-ALL-OFF",
            all(s == 0 for s in st) and any_fail == 0,
            enable=enable,
            window=w,
            words=2 * w,
            gen_status_all=[f"0x{s:02x}" for s in st],
            any_fail_count=any_fail,
            alert_threshold=thr,
            ht_status=f"0x{top:02x}",
        )
        close_graded_window(self.logger)

        await self._ht_ctrl(enable=HT_EN_REP | HT_EN_APT | HT_EN_MKV)
        await self._pattern_window(stuck, 2 * w, w)
        st = await self._gen_statuses()
        any_fail = await self._any_fail()
        want = enabled_bits(HT_EN_REP | HT_EN_APT | HT_EN_MKV)
        live = all(s & GRADED_BITS == want for s in st) and any_fail > 0
        self.chk.ctrl(
            "HT-ALL-OFF",
            live,
            enable=HT_EN_REP | HT_EN_APT | HT_EN_MKV,
            gen_status_all=[f"0x{s:02x}" for s in st],
            any_fail_count=any_fail,
        )

        v = self.plan.enable_drawn
        await self._ht_ctrl(enable=0)
        await self._clear_gen_statuses()
        pre = await self._gen_statuses()
        await self._ht_ctrl(enable=v)
        enable = ((await self._rd(A_HT_CTRL)) & M_HT_ENABLE) >> P_HT_ENABLE
        self.chk.ctrl(
            "HT-ENABLE-SET",
            all(s == 0 for s in pre) and enable == v,
            cleared_status=[f"0x{s:02x}" for s in pre],
            enable=enable,
            want_enable=v,
        )
        await self._pattern_window(stuck, 2 * w, w)
        st = await self._gen_statuses()
        want = enabled_bits(v)
        self.chk.ok(
            "HT-ENABLE",
            all(s & GRADED_BITS == want for s in st),
            tester="set",
            enable=v,
            want_bits=f"0x{want:02x}",
            window=w,
            gen_status_all=[f"0x{s:02x}" for s in st],
            ctrl_enabled_trips=int(live),
        )

    # --- threshold copy leg -----------------------------------------------------------
    async def _recommend(self, h: int) -> tuple[int, int, int]:
        """MIN_ENTROPY_H = ``h``; returns (H readback, RCT_LIMIT, APT_LIMIT)."""
        await self._wr(A_MIN_H, ENTROPY_SOURCE.value("MIN_ENTROPY_H", H=h))
        h_rb = ((await self._rd(A_MIN_H)) & M_MIN_H) >> P_MIN_H
        rec = await self._rd(A_REC)
        return h_rb, (rec & M_RCT) >> P_RCT, (rec & M_APT_REC) >> P_APT_REC

    async def _copied(self) -> tuple[int, int]:
        """(REPETITION_LIMIT, APT_PROPORTION_1BIT.LIMIT) read back."""
        rep = ((await self._rd(A_HT_CTRL)) & M_REP_LIMIT) >> P_REP_LIMIT
        apt = ((await self._rd(A_APT_1BIT)) & M_APT_1BIT) >> P_APT_1BIT
        return rep, apt

    async def _rec_trial(
        self, part: str, enable: int, pattern: LanePattern, words: int
    ) -> list[int]:
        """``pattern`` on all lanes for ``words`` with only ``enable`` testers on.

        The pattern changes while every tester is off, so no run or window that
        spans the change is tested. Returns the 12 generator statuses.
        """
        lanes = [pattern] * NUM_LANES
        await self._ht_ctrl(enable=0)
        await self._clear_gen_statuses()
        await self._pattern_window(lanes, SWITCH_WORDS, LIMIT_WINDOW)
        pre = await self._gen_statuses()
        await self._ht_ctrl(enable=enable)
        en = ((await self._rd(A_HT_CTRL)) & M_HT_ENABLE) >> P_HT_ENABLE
        self.chk.ctrl(
            "REC-COPY",
            all(s == 0 for s in pre) and en == enable,
            part=part,
            cleared_status=[f"0x{s:02x}" for s in pre],
            enable=en,
            want_enable=enable,
        )
        await self._pattern_window(lanes, words, LIMIT_WINDOW)
        return await self._gen_statuses()

    def _grade_rec(
        self, part: str, st: list[int], bit: int | None, ready: bool = True, **fields
    ) -> None:
        """Nothing latched (``bit`` None), or exactly ``bit`` in every generator."""
        want = 0 if bit is None else 1 << bit
        mask = M_GEN if bit is None else GRADED_BITS
        ok = ready and len(st) == NUM_LANES and all(s & mask == want for s in st)
        self.chk.ok(
            "REC-COPY",
            ok,
            part=part,
            expect="pass" if bit is None else f"bit{bit}",
            gen_status_all=[f"0x{s:02x}" for s in st],
            **fields,
        )

    async def _rec_copy_leg(self) -> None:
        """CHK-REC-COPY: RECOMMENDED_THRESHOLDS copied into the two limit registers."""
        w = LIMIT_WINDOW
        h = self.plan.rec_h
        await self._start(w)
        await self._ht_ctrl(enable=0)
        await self._wr(A_APT_LO, ENTROPY_SOURCE.value("APT_PROPORTION_LO", LIMIT=0))
        apt_lo = (await self._rd(A_APT_LO)) & M_APT_LO
        h_rb, c, a = await self._recommend(h)
        await self._ht_ctrl(rep_limit=c)
        await self._wr(A_APT_1BIT, ENTROPY_SOURCE.value("APT_PROPORTION_1BIT", LIMIT=a))
        rep, apt = await self._copied()
        usable = h_rb == h and apt_lo == 0 and c >= 1 and a + 1 <= w
        self.chk.ctrl(
            "REC-COPY",
            usable,
            part="recommend",
            h=f"0x{h:02x}",
            h_rb=f"0x{h_rb:02x}",
            rct_limit=c,
            apt_limit=a,
            apt_lo_limit=apt_lo,
            window=w,
        )
        self.chk.ok(
            "REC-COPY",
            rep == c and apt == a,
            part="copy",
            h=f"0x{h:02x}",
            rct_limit=c,
            apt_limit=a,
            repetition_limit=rep,
            apt_1bit_limit=apt,
        )
        if not usable:
            return

        # MIN_ENTROPY_H-only writes, up to the first code with another RCT_LIMIT.
        h2 = c2 = None
        tried = 0
        rb_ok = True
        for code in self.plan.rec_h_order:
            tried += 1
            rb, rct, _ = await self._recommend(code)
            rb_ok = rb_ok and rb == code
            if rct != c:
                h2, c2 = code, rct
                break
        rep, apt = await self._copied()
        self.chk.ctrl("REC-COPY", rb_ok and h2 is not None, part="new_rct", tried=tried, c2=c2)
        self.chk.ok(
            "REC-COPY",
            rep == c and apt == a,
            part="h_only",
            h_written=f"0x{h2:02x}" if h2 is not None else "na",
            repetition_limit=rep,
            apt_1bit_limit=apt,
            want=f"{c}_{a}",
        )

        def rep_words(run: int) -> int:
            # Two whole runs after the tester turns on, then a window boundary.
            return w + 2 * run + 2

        common = {"limit": c, "h_written": f"0x{h2:02x}" if h2 is not None else "na"}
        st = await self._rec_trial("rct_pass", HT_EN_REP, Square(c, 0), rep_words(c))
        self._grade_rec("rct_pass", st, None, run=c, **common)
        st = await self._rec_trial("rct_trip", HT_EN_REP, Square(c + 1, 0), rep_words(c + 1))
        self._grade_rec("rct_trip", st, BIT_REP, run=c + 1, **common)
        if c2 is not None:
            # The run length between C and C': it passes at one limit, trips at the other.
            run = c + 1 if c2 > c else c
            await self._ht_ctrl(rep_limit=c2)
            rep, _ = await self._copied()
            st = await self._rec_trial("flip", HT_EN_REP, Square(run, 0), rep_words(run))
            self._grade_rec(
                "flip",
                st,
                None if c2 > c else BIT_REP,
                ready=rep == c2,
                run=run,
                old_limit=c,
                limit=c2,
                repetition_limit=rep,
            )
        st = await self._rec_trial("apt_pass", HT_EN_APT, Spread(a, w), 2 * w)
        self._grade_rec("apt_pass", st, None, limit=a, ones=a, window=w)
        st = await self._rec_trial("apt_trip", HT_EN_APT, Spread(a + 1, w), 2 * w)
        self._grade_rec("apt_trip", st, BIT_APT, limit=a, ones=a + 1, window=w)

    # --- 32-bit tester legs -----------------------------------------------------------
    async def _top_regs(self) -> tuple[int, dict[str, int], int]:
        status = (await self._rd(A_HT_STATUS)) & M_HT_STATUS
        totals = {n: (await self._rd(a)) & M_TOTAL for n, a in A_TOTALS.items()}
        intr = (await self._rd(A_INTR_STATUS)) & M_HT_FAILED
        return status, totals, intr

    async def _zero_leg(self) -> int | None:
        """Constant zero with whitening on; returns APT_HI_TOTAL_FAILS after it."""
        w = RESET_WINDOW
        await self._start(w)
        s0, t0, i0 = await self._top_regs()
        pre_zero = s0 == 0 and all(v == 0 for v in t0.values()) and i0 == 0
        self.chk.ctrl(
            "HT-TOP-ZERO",
            pre_zero,
            status=f"0x{s0:02x}",
            totals=list(t0.values()),
            intr_health_failed=int(bool(i0)),
        )
        await self._write_reset_limits()
        open_graded_window(TEST, self.logger)
        await self._pattern_window([Stuck(0)] * NUM_LANES, 3 * w, w)
        s1, t1, i1 = await self._top_regs()
        ok = (
            (s1 >> BIT_APT) & 1 == 1
            and (s1 >> BIT_MKV_LO) & 1 == 1
            and t1["APT_LO_TOTAL_FAILS"] > 0
            and t1["MARKOV_LO_TOTAL_FAILS"] > 0
            and i1 == M_HT_FAILED
        )
        self.chk.ok(
            "HT-TOP-ZERO",
            ok,
            status=f"0x{s1:02x}",
            totals=f"{t1['REPCNT_TOTAL_FAILS']}_{t1['APT_LO_TOTAL_FAILS']}_"
            f"{t1['MARKOV_LO_TOTAL_FAILS']}",
            intr_health_failed=int(bool(i1)),
            ctrl_before=f"0x{s0:02x}",
        )
        bit4 = (s1 >> BIT_MKV_HI) & 1
        self.chk.ok(
            "HT-TOP-HI",
            bit4 == 0 and t1["APT_HI_TOTAL_FAILS"] == 0 and t1["MARKOV_HI_TOTAL_FAILS"] == 0,
            status=f"0x{s1:02x}",
            status_bit4=bit4,
            apt_hi_total=t1["APT_HI_TOTAL_FAILS"],
            mkv_hi_total=t1["MARKOV_HI_TOTAL_FAILS"],
            expect="0_0_0",
            window=w,
        )
        await self._presha(s1, t1["REPCNT_TOTAL_FAILS"], w)
        close_graded_window(self.logger)
        return t1["APT_HI_TOTAL_FAILS"]

    async def _presha(self, status: int, repcnt_total: int, window: int) -> None:
        """Whitener input words against digest words over a span between quiet clocks.

        architecture.adoc:142: 16 input words give 8 digest words. The tap
        (``env/sep_esrc_sha_tap.py``) traces every clock from the drained FIFO until
        PRESHA_PUSHES + PRESHA_TAIL input words; between its first and last quiet clock
        2 x output words == INPUT_COUNT(first) + input words - INPUT_COUNT(last).
        """
        dut = cocotb.top
        await self._drain()
        tap = SepEsrcShaTap(self.rd).start()
        bound = self._word_bound(PRESHA_PUSHES + PRESHA_TAIL, window)
        t0 = self._now()
        while tap.pushes < PRESHA_PUSHES + PRESHA_TAIL and self._now() - t0 <= bound:
            await RisingEdge(dut.clk_i)
        await tap.stop()
        pushes = tap.pushes
        words = []
        level = (await self._rd(A_FIFO_STATUS)) & M_FIFO_LEVEL
        for _ in range(level):
            words.append(await self._rd(A_FIFO_RDATA))
        self.chk.obs(
            "HT-PRESHA-WORDS",
            level=level,
            words=[f"0x{x:08x}" for x in words[:16]],
        )
        if pushes < PRESHA_PUSHES:
            self.chk.obs("HT-PRESHA-NOPUSH", pushes=pushes, stream_words=tap.words, bound=bound)
            self.chk.blocked("HT-PRESHA-NOPUSH", "whitener_input_after_post_boot_ht_fail_unstated")
            return
        span = tap.quiet_span()
        s = span or {"span_clk": 0, "in_first": 0, "in_last": 0, "in_words": 0, "out_words": 0}
        ctrl_bit0 = status & 1
        self.chk.ctrl(
            "HT-PRESHA",
            ctrl_bit0 == 1
            and repcnt_total > 0
            and span is not None
            and s["in_words"] >= BLOCK_WORDS
            and s["out_words"] >= DIGEST_WORDS,
            ctrl_status_bit0=ctrl_bit0,
            ctrl_repcnt_total=repcnt_total,
            span_in_words=s["in_words"],
            span_out_words=s["out_words"],
            min_in=BLOCK_WORDS,
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
            "pushes": pushes,
            "stream_words": tap.words,
        }
        if span is None:
            fields["reason"] = "no_quiet_span"
        self.chk.ok("HT-PRESHA", span is not None and 2 * s["out_words"] == absorbed, **fields)

    async def _bypass_zero_leg(self) -> None:
        """Constant zero with the compressor bypassed; the 32-bit tester result is logged.

        The windows are those of ``_zero_leg``. Which of architecture.adoc:47-48 (the
        32-bit test is clock-gated off in bypass) and architecture.adoc:122 (it
        monitors the post-bypass stream) holds is not settled, so the status and
        totals are OBS-ESRC-HT-BYPASS.
        """
        w = RESET_WINDOW
        try:
            await self._start(w, ctrl_fields={"BYPASS_ENTROPY_COMPRESSOR": 1})
            ctrl = await self._rd(A_CTRL)
            s0, t0, _ = await self._top_regs()
            await self._write_reset_limits()
            open_graded_window(TEST, self.logger)
            c0, m0 = self.noise.byte_control()
            await self._pattern_window([Stuck(0)] * NUM_LANES, 3 * w, w)
            c1, m1 = self.noise.byte_control()
            s1, t1, i1 = await self._top_regs()
        except (TrialTimeout, EsrcStrobeTimeout) as exc:
            close_graded_window(self.logger)
            self.noise.byte_check(False)
            self.chk.ctrl("ESRC-HT-BYPASS", False, reason=_timeout_reason(exc), bound=exc.bound)
            return
        bypass = (ctrl & M_CTRL_BYPASS) >> P_CTRL_BYPASS
        words = (c1 - c0) // NUM_LANES
        if self.chk.ctrl(
            "ESRC-HT-BYPASS",
            bypass == 1 and m1 == m0 and words >= w,
            ctrl=f"0x{ctrl:08x}",
            bypass=bypass,
            expect=1,
            words=words,
            mismatched=m1 - m0,
            window=w,
        ):
            set_open_value_leg_pass("esrc_ht_bypass_zero", self.logger)
            await ClockCycles(cocotb.top.clk_i, LEG_LABEL_CLKS)
            set_open_value_leg_pass(None, self.logger)
        close_graded_window(self.logger)
        self.chk.obs(
            "ESRC-HT-BYPASS",
            status=f"0x{s1:02x}",
            apt_bit3=(s1 >> BIT_APT) & 1,
            mkv_lo_bit5=(s1 >> BIT_MKV_LO) & 1,
            apt_lo_total=t1["APT_LO_TOTAL_FAILS"],
            mkv_lo_total=t1["MARKOV_LO_TOTAL_FAILS"],
            intr_health_failed=int(bool(i1)),
            status_before=f"0x{s0:02x}",
            totals_before=f"{t0['APT_LO_TOTAL_FAILS']}_{t0['MARKOV_LO_TOTAL_FAILS']}",
            window=w,
        )

    async def _ones_leg(self, apt_hi_zero: int | None) -> None:
        """Constant ones with the compressor in use and whitening off."""
        w = RESET_WINDOW
        await self._start(
            w, ctrl_fields={"BYPASS_ENTROPY_COMPRESSOR": 0, "SHA256_WHITENING_ENABLE": 0}
        )
        s0 = (await self._rd(A_HT_STATUS)) & M_HT_STATUS
        a0 = (await self._rd(A_TOTALS["APT_HI_TOTAL_FAILS"])) & M_TOTAL
        self.chk.ctrl("HT-TOP-ONE", s0 == 0 and a0 == 0, status=f"0x{s0:02x}", apt_hi_total=a0)
        await self._write_reset_limits()
        # entropy_source.adoc:336: zero disables the low-side test, so bit 3 of
        # HEALTH_TEST_STATUS can come only from the 32-bit high side.
        await self._wr(A_APT_LO, ENTROPY_SOURCE.value("APT_PROPORTION_LO", LIMIT=0))
        apt_lo = (await self._rd(A_APT_LO)) & M_APT_LO
        lo0 = (await self._rd(A_TOTALS["APT_LO_TOTAL_FAILS"])) & M_TOTAL
        await self._drain()
        open_graded_window(TEST, self.logger)
        await self._pattern_window([Stuck(1)] * NUM_LANES, 3 * w, w)
        s1 = (await self._rd(A_HT_STATUS)) & M_HT_STATUS
        a1 = (await self._rd(A_TOTALS["APT_HI_TOTAL_FAILS"])) & M_TOTAL
        lo1 = (await self._rd(A_TOTALS["APT_LO_TOTAL_FAILS"])) & M_TOTAL
        close_graded_window(self.logger)
        self.chk.ctrl(
            "HT-TOP-ONE-LO-OFF",
            apt_lo == 0 and lo1 == lo0,
            apt_lo_limit=apt_lo,
            apt_lo_total_before=lo0,
            apt_lo_total=lo1,
        )
        # Precondition: four FIFO words written after the stuck windows are one
        # constant non-zero word.
        await self._drain()
        bound = self._word_bound(w, 0)
        t0 = self._now()
        level = 0
        while self._now() - t0 <= bound:
            level = (await self._rd(A_FIFO_STATUS)) & M_FIFO_LEVEL
            if level >= 4:
                break
        words = [await self._rd(A_FIFO_RDATA) for _ in range(4)] if level >= 4 else []
        const = len(words) == 4 and len(set(words)) == 1 and words[0] != 0
        self.chk.ctrl(
            "HT-TOP-ONE-WORD",
            const,
            level=level,
            words=[f"0x{x:08x}" for x in words],
            bound=bound,
        )
        self.chk.ctrl(
            "HT-TOP-ONE-ZERO-LEG",
            apt_hi_zero == 0,
            ctrl_zero_leg_apt_hi=apt_hi_zero if apt_hi_zero is not None else "na",
        )
        fifo_word = words[0] if words else 0
        self.chk.ok(
            "HT-TOP-ONE",
            (s1 >> BIT_APT) & 1 == 1 and a1 > 0,
            fifo_word=f"0x{fifo_word:08x}",
            ones_lanes=bin(fifo_word).count("1"),
            window=w,
            apt_hi_limit=RESET_APT_1BIT,
            status=f"0x{s1:02x}",
            apt_hi_total=a1,
            ctrl_before=f"0x{s0:02x}",
            ctrl_zero_leg_apt_hi=apt_hi_zero if apt_hi_zero is not None else "na",
            ctrl_apt_lo_limit=apt_lo,
            ctrl_apt_lo_total=f"{lo0}_{lo1}",
        )
