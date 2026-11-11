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
divider value D_r (above the reset value, at most 1023), the order of 0 and
D_r in the period walk and the strobe (1 or 2 after a FIFO word) at which the
compressor bypass is set and cleared in ``OBS-COND-BYPASS-MIDGROUP``; after
those, the feedback-on mask class (few = 1 to 3 bits, half = 4, all = 0xFF) and
its mask, the lane L of ``CHK-COND-ONE-LANE``, the few (2 or 3) or half lane
set of ``OBS-COND-LANE-POP-FIFO`` and the start bit of each lane's alternating
fill before ``CHK-COND-LANES-OFF``.

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
                       gate, architecture.adoc:40-47; entropy_source.adoc:106). "Every
                       (N+1)th output" selects outputs N+1, 2(N+1), ...; for N >= 1 the
                       first output is not one of them. Control: no gated strobe before
                       the clean start returned and no FIFO word before the first gated
                       strobe.
  CHK-COND-PERIOD-RATIO  with every lane disabled, D written, then the lanes enabled,
                       the steady gap g_D of ``esrc_decor_valid_o`` meets
                       g_D x (D_ref + 1) == g_ref x (D + 1) for D = 0 and D_r against the
                       reset value D_ref (entropy_source.adoc:387; architecture.adoc:107).
                       A ratio of two DUT gaps: no time base.
  CHK-COND-FIRST-STROBE  the offset o_D = (distance from the clock where
                       ``esrc_ro_enable_o`` reads all ones to the first strobe) - g_D is
                       the same for D = 0 and D_r as for D_ref (architecture.adoc:113:
                       the divider holds at zero while disabled); a fixed enable delay
                       cancels. Control: 6 strobes after the enable, five equal gaps, no
                       strobe while disabled, and min(k, D) differs from
                       min(k', D_ref) for every count k a DUT that keeps its count
                       while disabled would hold at D and k' at D_ref (``held``, from
                       the divider trace): such a DUT gives an offset of
                       L - min(k, D), so it then fails.
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
  CHK-COND-SHA-STATUS-READS  every ``SHA256_STATUS`` bus read polled in the whitened
                       window after the first quiet clock of the status tap, with no
                       whitener input word and no FIFO word within ``QUIET_GUARD``
                       clocks of its bus window, holds the field meanings
                       (entropy_source.rdl:78, :83, :88; architecture.adoc:142, one
                       block is 16 words and gives 8 digest words). The count starts
                       at the first BUSY rise after the quiet clock, where a block of
                       16 words is complete. With n = 16 plus the input words from
                       that rise, and k the FIFO words from it: INPUT_COUNT == n mod
                       16; the INPUT_COUNT the tap reads at the quiet clock equals 16
                       minus the input words from it to the rise; BUSY == 1 when
                       8 x (n div 16) > k and 0 when equal; OUTPUT_COUNT == 0 when no
                       digest word is pending, == the pending words when a digest has
                       given some but not all of its words, and 0 or 8 when it has
                       given none. Digest words reach the FIFO with no backpressure
                       (architecture.adoc:148), so no quiet read falls inside the
                       output of a digest and no graded read expects a non-zero
                       OUTPUT_COUNT; the check grades the 0 only, and
                       CHK-COND-SHA-COUNT grades the count on the status tap. Control:
                       at least one graded read expects BUSY = 1 and one expects a
                       non-zero INPUT_COUNT.
  CHK-COND-PASSTHRU    every FIFO word == BIW observe word i + d at one d in 0..8.
                       Control ``CTRL-COND-REFLUSH``: FIFO_STATUS.LEVEL reads 0 after the
                       drain and the whitening switch, before FIFO_CTRL.ENABLE = 1.
  CHK-COND-DS-INTERVAL for N = 1 and N_r, compressor bypassed: each of DS_INTERVALS
                       consecutive output intervals, after SKIP_OUTPUTS outputs, holds
                       exactly N + 1 strobes of ``esrc_decor_valid_o``, graded one by one
                       (entropy_source.adoc:106). An interval is graded only when its
                       end output has three words and both ends lie the same number of
                       clocks after their last strobe.
  CHK-COND-DS-WORDS    at N_r, with constant lane bits that make the three words differ,
                       every output of the interval span is three words of
                       ``esrc_compress_data_o`` (the word written into the FIFO,
                       architecture.adoc:148) equal to the packing of the masked lane
                       bytes, word 0 first (architecture.adoc:118; entropy_source.adoc:108).
  CHK-COND-CTRL-CELL   for (BYPASS_ENTROPY_COMPRESSOR, SHA256_WHITENING_ENABLE) in (1, 1),
                       (1, 0), (0, 1), (0, 0) with FIFO_CTRL.ENABLE = 0: FIFO_STATUS LEVEL
                       and write pointer read before and after a window are equal while
                       ``esrc_compress_vld_o`` offers at least one word in it
                       (entropy_source.rdl FIFO_CTRL.ENABLE; architecture.adoc:150). The
                       window is 4 x (n + 1) strobe periods, n the strobes to the first
                       offered word: 16 with the compressor in use and whitening on (a
                       16-word block, architecture.adoc:142), else 1. The cell 100
                       write lands while the whitener hashes a block, so cell 010
                       also grades that SHA256_WHITENING_ENABLE = 1 conditions
                       blocks again (entropy_source.rdl SHA256_WHITENING_ENABLE):
                       its first offered word ends a full 16-word input block
                       (INPUT_COUNT at the window start plus the whitener input
                       words of the window).
                       Controls ``CTRL-COND-CTRL-CELL``: at least one offered word;
                       ``CTRL-COND-SHA-OFF-MID-HASH``: BUSY falls at the cell 100
                       write with no digest-output sample after the hash start.
  CHK-COND-DECOR-MASK  feedback on (DECORRELATOR_CTRL.BYPASS = 0), a drawn mask of class
                       few, half or all, compressor bypass 0 and 1: from the
                       ``esrc_decor_sr_o`` state before a start strobe, the 29-stage XOR
                       feedback chain stepped SAMPLE_CLK_DIV + 1 times per strobe with the
                       constant lane bits predicts each lane byte of DECOR_STROBES strobes,
                       stages [28:21] AND the mask, so a masked bit reads 0
                       (architecture.adoc:107, :113). With the compressor bypassed, the
                       words of each output between two graded strobes equal the packing
                       of its predicted bytes; with it in use only the bytes are graded.
                       Control: at least one predicted unmasked byte is non-zero.
  CHK-COND-LANES-OFF   every chain first filled with alternating lane bits (SAMPLE_CLK_DIV
                       0, a strobe per clk_i), then RING_OSC_ENABLE.ENABLE = 0: from the
                       first clock that ``esrc_ro_enable_o`` reads 0 to 4 x (reset
                       SAMPLE_CLK_DIV + 1) clocks after the divider write, no strobe of
                       ``esrc_decor_valid_o`` and all 12 slices of ``esrc_decor_sr_o`` and
                       ``esrc_decor_bytes_o`` equal their state at that first clock
                       (architecture.adoc:113: the chain holds while ``enable_i`` is low).
                       Control ``CTRL-COND-LANES-OFF``: every held chain holds both bit
                       values, so a shift changes it; the held chains are logged.
  CHK-COND-ONE-LANE    the live control of the same leg: only lane L enabled, its noise
                       bit the complement of its held stage 28, feedback bypassed: lane L's
                       ``esrc_decor_sr_o`` slice changes within RO_OFF_CLKS + 29 clocks and
                       the other 11 slices of both taps, which hold both bit values,
                       stay unchanged.
Logged only: ``OBS-COND-PASSTHRU-OUTCOUNT`` logs every
``SHA256_STATUS.OUTPUT_COUNT`` read polled in the pass-through window
(entropy_source.adoc:206 "remains 0 while idle or bypassed"). No bus read in the
whitened window shows the field non-zero, so a read of 0 does not tell a correct
field from one that is not connected; the status tap grades the count
(CHK-COND-SHA-COUNT). Also logged only: ``INFO-BLOCKED CHK-COND-HT-OFF`` (the
32-bit health test with the compressor bypassed has no single stated behaviour)
and ``INFO-BLOCKED CHK-COND-SHA-INTAKE`` (whether the whitener takes every BIW
word is not stated).
``OBS-COND-PERIOD-ABS`` logs the gap of each divider value in ``clk_i`` cycles
(the time base of the period is not stated: the register text names sample-clock
cycles, the architecture text ``clk_i`` cycles). No text states the effect of a
``DOWNSAMPLE_RATE`` or ``SAMPLE_CLK_DIV`` write while the stream runs, of a rate
written while the stream is stopped, or where the downsample count starts when
the compressor bypass turns on: ``OBS-COND-DS-MIDRUN-UP``,
``OBS-COND-DS-MIDRUN-DOWN``, ``OBS-COND-DIV-MIDRUN-UP``,
``OBS-COND-DIV-MIDRUN-DOWN``, ``OBS-COND-DS-RESUME`` and ``OBS-COND-DS-BYPASS-ON``
log the tapped counts and the distance to the next strobe or FIFO word. No text
states the FIFO words when the compressor bypass is set and cleared again
between two outputs of the compressor: ``OBS-COND-BYPASS-MIDGROUP`` logs the
FIFO words pushed between the two writes and the next three words.
No text states which input bytes and coefficients the BIW stage combines into
one word (architecture.adoc:115 names the grouping and the field only):
``OBS-ESRC-BIW-MAP`` logs, in the pass-through window, the first FIFO words on
``esrc_compress_data_o`` with the 12 lane bytes of the last two strobes before
each word, the clocks from the last strobe, and whether the word is in the BIW
observe words read after the window.
No text states the FIFO progress with only a part of the lanes enabled:
``OBS-COND-LANE-POP-FIFO`` logs the strobes, the offered words and FIFO LEVEL over
one window with a drawn few or half lane set.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_entropy_golden import BYTES_PER_WORD, SepEntropyGolden, bypass_pack_words
from env.sep_esrc_pattern_noise import (
    NUM_LANES,
    Alternate,
    Balanced,
    SepEsrcPatternNoise,
    Stuck,
    balanced_lanes,
    describe,
)
from env.sep_esrc_sha_tap import (
    BLOCK_WORDS,
    DIGEST_WORDS,
    IN_MASK,
    IN_SHIFT,
    OUT_MASK,
    OUT_SHIFT,
    QUIET_GUARD,
    SepEsrcShaTap,
)
from env.sep_fcov_gate import (
    ESRC_CNT_PASS_CTRL_CELL,
    ESRC_CNT_PASS_DECOR_MASK,
    ESRC_CNT_PASS_DS_INTERVAL,
    ESRC_CNT_PASS_FIRST_PUSH,
    ESRC_CNT_PASS_FIRST_STROBE,
    ESRC_CNT_PASS_LANES_OFF,
    ESRC_CNT_PASS_ONE_LANE,
    ESRC_CNT_PASS_PERIOD,
    close_graded_window,
    open_graded_window,
    set_esrc_cnt_pass,
)
from env.sep_seeded_rng import SepSeededRng
from models.entropy_decorrelator_model import SR_LENGTH
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
BIW_MAP_WORDS = 4  # FIFO words paired with their strobe bytes in OBS-ESRC-BIW-MAP
HT_WAIT_FACTOR = 3
# Period walk: strobes after a lane enable (the first distance and five gaps).
PERIOD_STROBES = 6
# Largest drawn divider value: a period walk value needs 7 periods of D + 1 clocks.
DIV_DRAW_MAX = 1023
# A rate above every drawn N_r (2 to 15), so N_r -> RATE_HI is an increase on every seed.
RATE_HI = 16
# Clocks the leaf holds a bit of esrc_cnt_pass before it writes 0.
CNT_HOLD_CLKS = 2
# Clean starts tried for a first push whose strobe counts can tell the count start.
FIRST_PUSH_TRIES = 3
# Reference walks tried for a held set without 0.
REF_WALK_TRIES = 3
# Clocks from a RING_OSC_ENABLE write of 0 to esrc_ro_enable_o reading 0 (outer cap).
RO_OFF_CLKS = 64
# Outer cap of the mid-run trace (clocks); never a contract.
MIDRUN_CAP = 200_000
# Output intervals graded one by one at the fixed rate and at N_r.
DS_INTERVAL_FIXED = 1
DS_INTERVALS = 7
# Lane bits of CHK-COND-DS-WORDS: word n holds n + 1 set lanes, so the three words
# differ for every non-zero mask and a word or byte swap changes the words.
DS_WORD_BITS = tuple(int(j % BYTES_PER_WORD <= j // BYTES_PER_WORD) for j in range(NUM_LANES))
# Strobes graded after the start strobe in CHK-COND-DECOR-MASK.
DECOR_STROBES = 8
DECOR_SKIP = 2  # strobes after the configuration writes before the start strobe
MASK_CLASSES = ("few", "half", "all")
MASK_BITS = 8
HALF_MASK_BITS = MASK_BITS // 2
FEW_MASK_BITS_MAX = 3
# CHK-COND-CTRL-CELL cells (BYPASS_ENTROPY_COMPRESSOR, SHA256_WHITENING_ENABLE), ENABLE = 0.
CTRL_CELLS = ((1, 1), (1, 0), (0, 1), (0, 0))
# Cell window: CELL_BOUND_FACTOR x (strobes to the first offered word + 1) strobe periods.
CELL_BOUND_FACTOR = 4
# SAMPLE_CLK_DIV of the chain fill before CHK-COND-LANES-OFF: a strobe on every clk_i.
FILL_DIV = 0
# Lane-population window of OBS-COND-LANE-POP-FIFO, in reset sample periods.
LANE_POP_PERIODS = 16
LANE_POP_CLASSES = ("few", "half")
FEW_LANES = (2, 3)
HALF_LANES = NUM_LANES // 2

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
# Clocks between two reference walks: half a reference period, so the disable of the
# next walk lands away from the count and the wrap that put 0 in the held set.
REF_WALK_SHIFT_CLKS = (RESET_DIV + 1) // 2


def _held(h: set[int] | None) -> str:
    return "none" if h is None else "/".join(str(v) for v in sorted(h))


def _first_push_tells(trace: dict) -> bool:
    """A count of every strobe from the TRNG release, or from the enable write, misses N+1.

    Such a count reaches N+1 on the first gated strobe j with (u + j) % (N+1) == 0,
    where u is the strobes it saw before the first gated one, so it pushes on strobe
    N+1 only when u % (N+1) == 0.
    """
    if trace["u0"] is None:
        return True
    m = trace["n"] + 1
    return trace["u0"] % m != 0 and (trace["u0"] - trace["u_at_ctrl"]) % m != 0


def _next_telling_rate(trace: dict) -> int:
    """The first rate after ``trace["n"]`` (15 wraps to 2) whose trace would tell, given its u0."""
    n = trace["n"]
    for k in range(1, RATE_HI - 2):
        c = 2 + (n - 2 + k) % (RATE_HI - 2)
        if _first_push_tells({**trace, "n": c}):
            return c
    return 2 + (n - 1) % (RATE_HI - 2)


def _lane_byte(bit: int, mask: int) -> int:
    return (0xFF if bit else 0x00) & mask


def _bypass_words(bits: list[int], mask: int) -> list[int]:
    """The three bypass words of constant lane bits under ``mask``."""
    return bypass_pack_words(_lane_byte(x, mask) for x in bits)


def _lanes(word: int, width: int) -> list[int]:
    """The 12 lane slices of a packed tap, lane 0 in the low bits."""
    return [(word >> (width * j)) & ((1 << width) - 1) for j in range(NUM_LANES)]


def _class_mask(rng: SepSeededRng, cls: str) -> int:
    if cls == "all":
        return (1 << MASK_BITS) - 1
    k = HALF_MASK_BITS if cls == "half" else rng.randrange(1, FEW_MASK_BITS_MAX + 1)
    return sum(1 << b for b in rng.sample(range(MASK_BITS), k))


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
    bypass_strobe: int
    decor_class: str
    decor_mask: int
    one_lane: int
    pop_class: str
    pop_lanes: int
    fill_starts: int

    @property
    def rates(self) -> tuple[int, ...]:
        return tuple(sorted((0, 1, self.n_r, 1023)))

    def describe(self) -> str:
        return (
            f"legs={','.join(self.legs)} mask=0x{self.mask:02x} n_r={self.n_r} "
            f"z=0x{self.z:03x} rates={list(self.rates)} div_r={self.div_r} "
            f"div_walk={list(self.div_walk)} bypass_strobe={self.bypass_strobe} "
            f"decor_mask={self.decor_class}:0x{self.decor_mask:02x} one_lane={self.one_lane} "
            f"pop_lanes={self.pop_class}:0x{self.pop_lanes:03x} "
            f"fill_starts=0x{self.fill_starts:03x} {describe(self.balanced)}"
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
    bypass_strobe = rng.choice((1, 2))
    decor_class = rng.choice(MASK_CLASSES)
    decor_mask = _class_mask(rng, decor_class)
    one_lane = rng.randrange(NUM_LANES)
    pop_class = rng.choice(LANE_POP_CLASSES)
    k = HALF_LANES if pop_class == "half" else rng.choice(FEW_LANES)
    pop_lanes = sum(1 << j for j in rng.sample(range(NUM_LANES), k))
    fill_starts = rng.getrandbits(NUM_LANES)
    return Plan(
        seed,
        tuple(legs),
        mask,
        n_r,
        z,
        balanced,
        div_r,
        (RESET_DIV, *tail),
        bypass_strobe,
        decor_class,
        decor_mask,
        one_lane,
        pop_class,
        pop_lanes,
        fill_starts,
    )


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
        "CHK-COND-SHA-STATUS-READS",
        "CHK-COND-PASSTHRU",
        "CHK-COND-FIRST-PUSH",
        "CHK-COND-PERIOD-RATIO",
        "CHK-COND-FIRST-STROBE",
        "CHK-COND-DS-INTERVAL",
        "CHK-COND-DS-WORDS",
        "CHK-COND-CTRL-CELL",
        "CHK-COND-DECOR-MASK",
        "CHK-COND-LANES-OFF",
        "CHK-COND-ONE-LANE",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=PARK)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("INFO-PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.esrc = _EsrcRegs(self)
        self.p: int | None = None
        self.logger.info("INFO-BASELINE sw_reset_n=0x%02x", self.swrst.value)
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
                2 * WINDOW + 64 + MAX_PRE_CLEAN_STROBES + 2 * RATE_HI
            ) * RESET_STROBE_CLK + PERIOD_CAP
            trace = {
                "g": 0,
                "u": 0,
                "u0": None,
                "pre_push": 0,
                "k": None,
                "ds_count": None,
                "reason": "",
            }
            trace["task"] = cocotb.start_soon(self._first_push_trace(trace, bound))
        await self._wr(ESRC_INTR_ENABLE, INTR_ENABLE_ALL)
        await self._wr(ESRC_ALERT_THRESHOLD, _val("ALERT_THRESHOLD", THRESHOLD=0))
        await SepEsrcCleanStart(
            self, self.noise, self.plan.balanced, window=WINDOW, ctrl_fields=ctrl_fields
        ).run(release_mark=mark)
        if trace is not None:
            trace["gated_at_ctrl"] = trace["g"]
            trace["u_at_ctrl"] = trace["u"]
        self.p = await self.setup.measure_period(self.chk)
        await self.setup.wait_boot_done(self.esrc, WINDOW)
        return trace

    async def _first_push_trace(self, st: dict, bound: int) -> None:
        """Counts ``esrc_stream_valid_gated_o`` strobes up to the first FIFO word.

        On every ``clk_i`` (ReadOnly): ``g`` counts the gated strobes and ``u`` the
        ungated ``esrc_decor_valid_o`` strobes; ``u0`` = ``u`` before the first gated
        strobe; a word of
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
                if st["g"] == 0:
                    st["u0"] = st["u"]
                st["g"] += 1
            if self.rd(dut.esrc_decor_valid_o):
                st["u"] += 1
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
        self.logger.info(
            "INFO-COND-SETTLE strobes=%d clocks=%d", SETTLE_STROBES, self._now() - c_change
        )

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
        for bypass in (0, 1):
            await self._decor_mask(bits, bypass)
        await self._lane_population(bits)
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

    async def _decor_trace(self, count: int, skip: int) -> tuple[list, list]:
        """``count`` strobes of ``esrc_decor_valid_o`` after ``skip``, and the words between.

        On every clk_i (ReadOnly) a strobe records (``esrc_decor_sr_o`` of the clock
        before, ``esrc_decor_bytes_o``, clock): the output register takes the stages
        before the edge (architecture.adoc:107). From the first recorded strobe on,
        each word of ``esrc_compress_vld_o`` records (clock, ``esrc_compress_data_o``).
        """
        dut = cocotb.top
        strobes: list[tuple[int, int, int]] = []
        words: list[tuple[int, int]] = []
        prev_sr = None
        seen = 0
        for clk in range((count + skip + 2) * self._period() * 4):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.esrc_decor_valid_o):
                seen += 1
                if seen > skip and prev_sr is not None:
                    strobes.append((prev_sr, self.rd(dut.esrc_decor_bytes_o), clk))
                    if len(strobes) == count:
                        break
            if strobes and self.rd(dut.esrc_compress_vld_o):
                words.append((clk, self.rd(dut.esrc_compress_data_o)))
            prev_sr = self.rd(dut.esrc_decor_sr_o)
        await NextTimeStep()
        return strobes, words

    async def _decor_mask(self, bits: list[int], bypass: int) -> None:
        """CHK-COND-DECOR-MASK: lane bytes of the feedback chain under the drawn mask.

        architecture.adoc:107: each sampled bit enters a 29-stage chain with XOR
        feedback from the last stage; the byte is stages [28:21] every SAMPLE_CLK_DIV
        + 1 clk_i cycles, ANDed with the mask. With DECORRELATOR_CTRL.BYPASS = 0
        (entropy_source.rdl DECORRELATOR_CTRL.BYPASS) and constant lane bits, the
        stage state before one start strobe fixes every later byte. The model is
        ``SepEntropyGolden``'s decorrelator, seeded with that state only. With the
        compressor bypassed (``bypass``), output k is three words written from the
        clock of its strobe to the next (architecture.adoc:118).
        """
        plan = self.plan
        mask = plan.decor_mask
        decor = _val("DECORRELATOR_CTRL", BYPASS=0, SAMPLE_CLK_DIV=RESET_DIV)
        mask_v = _val("DECORRELATOR_MASK", ENTROPY_BYTE_MASK=mask)
        ctrl = _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=bypass, SHA256_WHITENING_ENABLE=0)
        await self._wr(ESRC_DECORRELATOR_CTRL, decor)
        await self._wr(ESRC_DECORRELATOR_MASK, mask_v)
        await self._wr(ESRC_CTRL, ctrl)
        rb = (
            await self._rd(ESRC_DECORRELATOR_CTRL),
            await self._rd(ESRC_DECORRELATOR_MASK),
            await self._rd(ESRC_CTRL),
        )
        strobes, words = await self._decor_trace(DECOR_STROBES + 1, DECOR_SKIP)
        noise = sum(b << j for j, b in enumerate(bits))
        model = SepEntropyGolden(sample_clk_div=RESET_DIV, byte_mask=mask, sha_whitening=False)
        predicted: list[int] = []
        got: list[int] = []
        if len(strobes) == DECOR_STROBES + 1:
            model.seed_decor_sr(strobes[0][0])
            for _, dut_bytes, _ in strobes[1:]:
                for _ in range(RESET_DIV + 1):
                    model.feed_noise(noise)
                predicted.append(
                    sum(
                        (b & mask) << (8 * j)
                        for j, b in enumerate(_lanes(model.decor_sr_word(), 8))
                    )
                )
                got.append(dut_bytes)
        byte_bad = sum(
            1 for p, g in zip(predicted, got) for a, b in zip(_lanes(p, 8), _lanes(g, 8)) if a != b
        )
        masked_set = sum(1 for g in got for b in _lanes(g, 8) if b & ~mask)
        nonzero = sum(1 for p in predicted for b in _lanes(p, 8) if b)
        word_bad = 0
        word_groups = 0
        if bypass and predicted:
            clks = [s[2] for s in strobes]
            for k in range(1, DECOR_STROBES):
                group = [w for c, w in words if clks[k] <= c < clks[k + 1]]
                word_groups += 1
                expect = bypass_pack_words(_lanes(predicted[k - 1], 8))
                word_bad += int(group != expect)
        gaps = sorted({b[2] - a[2] for a, b in zip(strobes, strobes[1:])})
        self.chk.ctrl(
            "COND-DECOR-MASK",
            rb == (decor, mask_v, ctrl) and len(predicted) == DECOR_STROBES and nonzero > 0,
            bypass=bypass,
            mask_class=plan.decor_class,
            decor_ctrl_rb=f"0x{rb[0]:08x}",
            mask_rb=f"0x{rb[1]:02x}",
            ctrl_rb=f"0x{rb[2]:08x}",
            strobes=len(predicted),
            nonzero_predicted_bytes=nonzero,
            word_groups=word_groups,
        )
        ok = self.chk.ok(
            "COND-DECOR-MASK",
            len(predicted) == DECOR_STROBES
            and byte_bad == 0
            and masked_set == 0
            and (not bypass or (word_groups == DECOR_STROBES - 1 and word_bad == 0)),
            bypass=bypass,
            mask_class=plan.decor_class,
            mask=f"0x{mask:02x}",
            noise=f"0x{noise:03x}",
            strobes=len(predicted),
            gaps=gaps,
            byte_mismatches=byte_bad,
            masked_bits_set=masked_set,
            nonzero_predicted_bytes=nonzero,
            word_groups=word_groups,
            word_group_mismatches=word_bad,
            predicted=[f"0x{p:024x}" for p in predicted],
            dut=[f"0x{g:024x}" for g in got],
        )
        if ok:
            await self._cnt_pass(ESRC_CNT_PASS_DECOR_MASK)

    async def _lane_population(self, bits: list[int]) -> None:
        """CHK-COND-LANES-OFF, CHK-COND-ONE-LANE and OBS-COND-LANE-POP-FIFO.

        architecture.adoc:113: the chain shifts on every clk_i while ``enable_i`` is
        high and holds while it is low; RING_OSC_ENABLE.ENABLE is the enable of each
        generator (entropy_source.adoc:357), and ``esrc_ro_enable_o`` is that enable.
        First every chain is filled with alternating bits (``_fill_chains``), so each
        held chain holds both bit values and any shift, whatever the input bit,
        changes it. Then every lane is turned off: the chain state on the first clock
        that ``esrc_ro_enable_o`` reads 0 is the state at disable, and on every later
        clock up to four reset byte periods after the SAMPLE_CLK_DIV write both taps
        equal that state and no strobe comes. Then only lane L is enabled, feedback
        bypassed, with its noise bit the complement of its held stage 28: its slice
        changes and the other 11 slices hold. That window starts at the
        RING_OSC_ENABLE write response and lasts RO_OFF_CLKS (the enable path) + 29
        clocks.
        """
        plan = self.plan
        dut = cocotb.top
        lane = plan.one_lane
        fill_strobes = await self._fill_chains()
        decor = _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL, SAMPLE_CLK_DIV=RESET_DIV)
        window = 4 * (RESET_DIV + 1)
        rows: list[tuple[int, int, int, int]] = []
        run = [True]

        async def _off_trace() -> None:
            while run[0]:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                rows.append(
                    (
                        self.rd(dut.esrc_ro_enable_o),
                        self.rd(dut.esrc_decor_sr_o),
                        self.rd(dut.esrc_decor_bytes_o),
                        self.rd(dut.esrc_decor_valid_o),
                    )
                )
            await NextTimeStep()

        trace = cocotb.start_soon(_off_trace())
        off = await self._lanes_off()
        await self._wr(ESRC_DECORRELATOR_CTRL, decor)
        decor_rb = await self._rd(ESRC_DECORRELATOR_CTRL)
        ro_rb = await self._rd(ESRC_RING_OSC_ENABLE)
        await ClockCycles(dut.clk_i, window)
        run[0] = False
        await trace
        d = next((i for i, r in enumerate(rows) if r[0] == 0), None)
        _, held_sr, held_bytes, _ = rows[d] if d is not None else rows[-1]
        after = rows[d + 1 :] if d is not None else []
        held_lanes = _lanes(held_sr, SR_LENGTH)
        held_by = _lanes(held_bytes, 8)
        strobes = sum(r[3] for r in after)
        sr_changed = {
            j
            for r in after
            for j, (a, b) in enumerate(zip(_lanes(r[1], SR_LENGTH), held_lanes))
            if a != b
        }
        byte_changed = {
            j for r in after for j, (a, b) in enumerate(zip(_lanes(r[2], 8), held_by)) if a != b
        }
        constant = [j for j, v in enumerate(held_lanes) if v in (0, (1 << SR_LENGTH) - 1)]
        held_hex = [f"0x{v:08x}" for v in held_lanes]
        self.chk.ctrl(
            "COND-LANES-OFF",
            d is not None and not constant,
            fill_strobes=fill_strobes,
            constant_lanes=constant,
            held_sr=held_hex,
        )
        ro_off = _get(ro_rb, "RING_OSC_ENABLE", "ENABLE")
        if self.chk.ok(
            "COND-LANES-OFF",
            d is not None
            and ro_off == 0
            and decor_rb == decor
            and len(after) >= window
            and strobes == 0
            and not sr_changed
            and not byte_changed,
            ro_enable_rb=f"0x{ro_off:03x}",
            off_clk="none" if off is None else off,
            window_clk=window,
            held_clk=len(after),
            strobes=strobes,
            held_sr=held_hex,
            sr_changed_lanes=sorted(sr_changed),
            byte_changed_lanes=sorted(byte_changed),
        ):
            await self._cnt_pass(ESRC_CNT_PASS_LANES_OFF)

        # One lane: the bit that differs from its held stage 28.
        b = 1 - ((held_lanes[lane] >> (SR_LENGTH - 1)) & 1)
        one = list(bits)
        one[lane] = b
        self.noise.set_lanes([Stuck(x) for x in one], immediate=True)
        ro_one = _val("RING_OSC_ENABLE", ENABLE=1 << lane)
        await self._wr(ESRC_RING_OSC_ENABLE, ro_one)
        bound = RO_OFF_CLKS + SETTLE_CLOCKS
        first = None
        others_sr: set[int] = set()
        others_bytes: set[int] = set()
        for clk in range(1, bound + 1):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            sr = _lanes(self.rd(dut.esrc_decor_sr_o), SR_LENGTH)
            by = _lanes(self.rd(dut.esrc_decor_bytes_o), 8)
            if first is None and sr[lane] != held_lanes[lane]:
                first = clk
            others_sr |= {j for j in range(NUM_LANES) if j != lane and sr[j] != held_lanes[j]}
            others_bytes |= {j for j in range(NUM_LANES) if j != lane and by[j] != held_by[j]}
        await NextTimeStep()
        ro_one_rb = await self._rd(ESRC_RING_OSC_ENABLE)
        if self.chk.ok(
            "COND-ONE-LANE",
            ro_one_rb == ro_one and first is not None and not others_sr and not others_bytes,
            lane=lane,
            noise_bit=b,
            held_sr=f"0x{held_lanes[lane]:08x}",
            ro_enable_rb=f"0x{ro_one_rb:08x}",
            first_change_clk="none" if first is None else first,
            bound_clk=bound,
            other_sr_changed=sorted(others_sr),
            other_byte_changed=sorted(others_bytes),
        ):
            await self._cnt_pass(ESRC_CNT_PASS_ONE_LANE)
        await self._lane_pop_fifo()
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))

    async def _fill_chains(self) -> int:
        """Alternating lane bits through every chain; returns the strobes with the lanes on.

        Lanes off, then (no strobe comes) each lane j gets ``Alternate`` with the drawn
        start bit j, DECORRELATOR_CTRL = feedback bypassed with SAMPLE_CLK_DIV =
        FILL_DIV, lanes on. A strobe comes on every clk_i (architecture.adoc:107) and the
        noise driver gives each lane its next bit at each strobe, so after SR_LENGTH + 1
        strobes the 29 stages of every chain alternate.
        """
        plan = self.plan
        if await self._lanes_off() is None:
            raise AssertionError(f"esrc_ro_enable_o not 0 bound={RO_OFF_CLKS}")
        self.noise.set_lanes(
            [Alternate((plan.fill_starts >> j) & 1) for j in range(NUM_LANES)], immediate=True
        )
        await self._wr(
            ESRC_DECORRELATOR_CTRL,
            _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL, SAMPLE_CLK_DIV=FILL_DIV),
        )
        mark = self.noise.mark()
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE"))
        await self.noise.wait_words(
            SR_LENGTH + 1, RO_OFF_CLKS + CELL_BOUND_FACTOR * (SR_LENGTH + 1) * (FILL_DIV + 1)
        )
        return self.noise.words_since(mark)

    async def _lane_pop_fifo(self) -> None:
        """OBS-COND-LANE-POP-FIFO: strobes, offered words and LEVEL with a part of the lanes.

        Compressor in use, whitening off, FIFO drained and then enabled for
        LANE_POP_PERIODS reset byte periods. No text states the rate; logged only.
        """
        plan = self.plan
        dut = cocotb.top
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._wr(ESRC_CTRL, _val("CTRL", SHA256_WHITENING_ENABLE=0))
        await self._wr(ESRC_RING_OSC_ENABLE, _val("RING_OSC_ENABLE", ENABLE=plan.pop_lanes))
        await self._drain_fifo("FIFO_STATUS", ESRC_FIFO_RDATA, ESRC_FIFO_STATUS)
        before = _get(await self._rd(ESRC_FIFO_STATUS), "FIFO_STATUS", "LEVEL")
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        window = LANE_POP_PERIODS * (RESET_DIV + 1)
        strobes = words = 0
        for _ in range(window):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            strobes += self.rd(dut.esrc_decor_valid_o)
            words += self.rd(dut.esrc_compress_vld_o)
        await NextTimeStep()
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        after = _get(await self._rd(ESRC_FIFO_STATUS), "FIFO_STATUS", "LEVEL")
        self.chk.obs(
            "COND-LANE-POP-FIFO",
            lane_class=plan.pop_class,
            lanes=f"0x{plan.pop_lanes:03x}",
            window_clk=window,
            strobes=strobes,
            offered_words=words,
            level_before=before,
            level_after=after,
        )

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
            ctrl = _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, SHA256_WHITENING_ENABLE=whiten)
            await self._wr(ESRC_CTRL, ctrl)
            ctrl_rb = await self._rd(ESRC_CTRL)
            self.chk.ctrl(
                "COND-BYPASS",
                ctrl_rb == ctrl,
                whiten=whiten,
                ctrl=f"0x{ctrl:08x}",
                ctrl_rb=f"0x{ctrl_rb:08x}",
            )
            for pas in SIGNATURE_PASSES:
                if not await self._bypass_pass(ctrl_rb, pas):
                    close_graded_window(self.logger)
                    return
        close_graded_window(self.logger)

    async def _bypass_pass(self, ctrl_rb: int, pas) -> bool:
        plan = self.plan
        whiten = _get(ctrl_rb, "CTRL", "SHA256_WHITENING_ENABLE")
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
        n = plan.n_r
        for tries in range(1, FIRST_PUSH_TRIES + 1):
            trace = await self._setup(
                ctrl_fields={"BYPASS_ENTROPY_COMPRESSOR": 1, "DOWNSAMPLE_RATE": n},
                first_push=True,
            )
            await trace["task"]
            trace.update(n=n, tries=tries)
            if _first_push_tells(trace):
                break
            n = _next_telling_rate(trace)
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
        await self._ds_intervals()
        await self._ctrl_cells()
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

    async def _aligned_span(
        self, per_output: int, outputs: int, n: int, prev: int, capture: dict | None = None
    ) -> dict:
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

        With ``capture``, it also receives ``groups``, ``data`` (the
        ``esrc_compress_data_o`` words of each group) and ``strobe_clks``.
        """
        dut = cocotb.top
        reach = (prev + 1) + (SKIP_OUTPUTS + outputs + 2) * (n + 1) + 8
        clock_cap = 4 * reach * self._period()
        need = SKIP_OUTPUTS + outputs
        clk = 0
        strobes = 0
        strobe_clks: list[int] = []
        groups: list[tuple[int, int, int]] = []  # (words, last word clock, strobes then)
        data: list[list[int]] = []
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
                    data.append([])
                cur[0] += 1
                cur[1] = clk
                cur[2] = strobes
                if capture is not None:
                    data[-1].append(self.rd(dut.esrc_compress_data_o))
        await NextTimeStep()
        if capture is not None:
            capture.update(groups=groups, data=data, strobe_clks=strobe_clks, reason=reason)
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

    async def _ds_intervals(self) -> None:
        """CHK-COND-DS-INTERVAL at N = 1 and N_r, CHK-COND-DS-WORDS at N_r.

        entropy_source.adoc:106: DOWNSAMPLE_RATE = N selects every (N+1)th
        decorrelator output while BIW extraction is bypassed, so each interval
        between the ends of two selected outputs holds N + 1 strobes. The interval
        between the last words of two outputs is exact when both lie the same
        number of clocks after their last strobe. The lane bits are DS_WORD_BITS
        with feedback bypassed and the mask M, so every selected output is the same
        three words (architecture.adoc:118), and they differ from each other.
        """
        plan = self.plan
        await self._wr(
            ESRC_DECORRELATOR_MASK, _val("DECORRELATOR_MASK", ENTROPY_BYTE_MASK=plan.mask)
        )
        mask_rb = _get(
            await self._rd(ESRC_DECORRELATOR_MASK), "DECORRELATOR_MASK", "ENTROPY_BYTE_MASK"
        )
        await self._drive_stuck(list(DS_WORD_BITS))
        expect = _bypass_words(list(DS_WORD_BITS), plan.mask)
        prev = 0
        for n in (DS_INTERVAL_FIXED, plan.n_r):
            ctrl = _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=n)
            await self._wr(ESRC_CTRL, ctrl)
            cap: dict = {}
            await self._aligned_span(BYPASS_WORDS, DS_INTERVALS, n, prev, capture=cap)
            ctrl_rb = await self._rd(ESRC_CTRL)
            prev = n
            groups, clks = cap["groups"], cap["strobe_clks"]
            ends = groups[SKIP_OUTPUTS - 1 : SKIP_OUTPUTS + DS_INTERVALS]

            def phase(g, clks=clks):
                return g[1] - max((s for s in clks if s <= g[1]), default=g[1])

            passed = 0
            for i in range(DS_INTERVALS):
                fields: dict = {"n": n, "interval": i, "expect_strobes": n + 1}
                if i + 1 >= len(ends):
                    fields["reason"] = cap["reason"] or "outputs_missing"
                    self.chk.ok("COND-DS-INTERVAL", False, **fields)
                    continue
                a, b = ends[i], ends[i + 1]
                fields.update(
                    strobes=b[2] - a[2],
                    words=f"{a[0]}_{b[0]}",
                    phase=f"{phase(a)}_{phase(b)}",
                    ctrl_rb=f"0x{ctrl_rb:08x}",
                )
                passed += self.chk.ok(
                    "COND-DS-INTERVAL",
                    ctrl_rb == ctrl
                    and a[0] == b[0] == BYPASS_WORDS
                    and phase(a) == phase(b)
                    and b[2] - a[2] == n + 1,
                    **fields,
                )
            if passed == DS_INTERVALS:
                await self._cnt_pass(ESRC_CNT_PASS_DS_INTERVAL)
            if n != plan.n_r:
                continue
            outs = cap["data"][SKIP_OUTPUTS : SKIP_OUTPUTS + DS_INTERVALS]
            bad = sum(1 for w in outs if w != expect)
            self.chk.ok(
                "COND-DS-WORDS",
                len(outs) == DS_INTERVALS and bad == 0 and mask_rb == plan.mask,
                n=n,
                mask=f"0x{plan.mask:02x}",
                mask_rb=f"0x{mask_rb:02x}",
                lane_bits=f"0x{sum(b << j for j, b in enumerate(DS_WORD_BITS)):03x}",
                outputs=len(outs),
                mismatches=bad,
                words=[f"0x{w:08x}" for w in (outs[0] if outs else [])],
                expect=[f"0x{w:08x}" for w in expect],
            )
        await self._wr(ESRC_CTRL, _val("CTRL"))

    async def _ctrl_cells(self) -> None:
        """CHK-COND-CTRL-CELL: no FIFO write in the four FIFO_CTRL.ENABLE = 0 cells.

        entropy_source.rdl FIFO_CTRL.ENABLE "Enables FIFO writes ... Words offered to
        the FIFO are also the DRBG seed stream, which this field does not gate";
        architecture.adoc:148, :150: ``esrc_compress_vld_o`` carries each offered
        word and ENABLE gates only the FIFO write. Per cell, after a drain, FIFO_STATUS
        is read before and after a window that holds at least one offered word;
        LEVEL and the write pointer (WPTR) stay. The offered words come from the
        running lanes under the noise driver.

        The window is CELL_BOUND_FACTOR x (n + 1) strobe periods, where n is the
        strobes to the first offered word: one, for a bypassed output (DOWNSAMPLE_RATE
        0, entropy_source.adoc:106) or a BIW word passed through (one BIW word per
        strobe, architecture.adoc:115); BLOCK_WORDS with the compressor in use and
        whitening on, since the whitener gives no word before a block of 16 input
        words (architecture.adoc:142).
        """
        dut = cocotb.top
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        fifo_en = _get(await self._rd(ESRC_FIFO_CTRL), "FIFO_CTRL", "ENABLE")
        for bypass, sha in CTRL_CELLS:
            need = BLOCK_WORDS if (bypass, sha) == (0, 1) else 1
            cap = CELL_BOUND_FACTOR * (need + 1) * self._period()
            ctrl = _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=bypass, SHA256_WHITENING_ENABLE=sha)
            if (bypass, sha) == (1, 0):
                await self._sha_off_mid_hash(ctrl)
            else:
                await self._wr(ESRC_CTRL, ctrl)
            ctrl_rb = await self._rd(ESRC_CTRL)
            await self._drain_fifo("FIFO_STATUS", ESRC_FIFO_RDATA, ESRC_FIFO_STATUS)
            st_a = await self._rd(ESRC_FIFO_STATUS)
            words = strobes = pushes = 0
            in_start = None
            for _ in range(cap):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                if in_start is None:
                    in_start = (self.rd(dut.esrc_sha256_status_o) >> IN_SHIFT) & IN_MASK
                strobes += self.rd(dut.esrc_decor_valid_o)
                pushes += self.rd(dut.esrc_whiten_push_o)
                words += self.rd(dut.esrc_compress_vld_o)
                if words:
                    break
            await NextTimeStep()
            st_b = await self._rd(ESRC_FIFO_STATUS)
            sha_rb = await self._rd(ESRC_SHA256_STATUS)
            cell = f"{bypass}{sha}0"
            # Whitened cell: the first offered word ends a full 16-word input block.
            block_ok = (bypass, sha) != (0, 1) or in_start + pushes >= BLOCK_WORDS
            self.chk.ctrl(
                "COND-CTRL-CELL",
                words >= 1 and ctrl_rb == ctrl and fifo_en == 0,
                cell=cell,
                offered_words=words,
                need_strobes=need,
                bound_clk=cap,
                strobes=strobes,
                whiten_pushes=pushes,
                sha_status_rb=f"0x{sha_rb:08x}",
                ctrl_rb=f"0x{ctrl_rb:08x}",
                fifo_enable_rb=fifo_en,
            )
            level_a = _get(st_a, "FIFO_STATUS", "LEVEL")
            level_b = _get(st_b, "FIFO_STATUS", "LEVEL")
            wptr_a = _get(st_a, "FIFO_STATUS", "WPTR")
            wptr_b = _get(st_b, "FIFO_STATUS", "WPTR")
            if self.chk.ok(
                "COND-CTRL-CELL",
                words >= 1
                and block_ok
                and level_a < FIFO_DEPTH
                and level_b == level_a
                and wptr_b == wptr_a,
                cell=cell,
                offered_words=words,
                input_count_start=in_start,
                whiten_pushes=pushes,
                level_before=level_a,
                level_after=level_b,
                wptr_before=wptr_a,
                wptr_after=wptr_b,
            ):
                await self._cnt_pass(ESRC_CNT_PASS_CTRL_CELL[(bypass, sha)])
        await self._wr(ESRC_CTRL, _val("CTRL"))

    async def _sha_off_mid_hash(self, ctrl: int) -> None:
        """Land the cell 100 SHA-off write while the whitener hashes a block.

        ``esrc_sha256_status_o`` is {OUTPUT_COUNT, INPUT_COUNT, BUSY}. BUSY with
        OUTPUT_COUNT 0 is the hash phase; BUSY with OUTPUT_COUNT 8 to 1 is the digest
        output, which does not stall. The write lands mid-hash when BUSY falls with no
        digest-output sample between the hash start and the fall. Cell 010 that follows
        then grades that SHA256_WHITENING_ENABLE = 1 conditions blocks again
        (entropy_source.rdl SHA256_WHITENING_ENABLE).
        """
        dut = cocotb.top
        cap = CELL_BOUND_FACTOR * (BLOCK_WORDS + 1) * self._period()
        hashing = False
        wait_clk = 0
        while wait_clk < cap and not hashing:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            wait_clk += 1
            st = self.rd(dut.esrc_sha256_status_o)
            hashing = bool(st & 1) and (st >> OUT_SHIFT) & OUT_MASK == 0
        samples: list[int] = []

        async def _trace() -> None:
            for _ in range(cap):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                samples.append(self.rd(dut.esrc_sha256_status_o))
                if not samples[-1] & 1:
                    return

        trace = cocotb.start_soon(_trace())
        await NextTimeStep()
        await self._wr(ESRC_CTRL, ctrl)
        await trace
        fell = bool(samples) and not samples[-1] & 1
        out_seen = any((s >> OUT_SHIFT) & OUT_MASK for s in samples)
        self.chk.ctrl(
            "COND-SHA-OFF-MID-HASH",
            hashing and fell and not out_seen,
            wait_clk=wait_clk,
            fall_clk=len(samples),
            digest_output_seen=int(out_seen),
            bound_clk=cap,
        )

    # --- first push, period walk and mid-run writes (downsample leg) -------------
    async def _grade_first_push(self, trace: dict) -> None:
        """CHK-COND-FIRST-PUSH: the first FIFO word on the (N_r+1)th gated strobe.

        entropy_source.adoc:106: DOWNSAMPLE_RATE = N selects every (N+1)th
        decorrelator output while BIW extraction is bypassed, that is outputs N+1,
        2(N+1), ..., so for N >= 1 the first output is not selected; architecture.adoc:40-47:
        the boot gate passes the uncompressed bytes only after a passing boot window,
        and the output select downsamples them by DOWNSAMPLE_RATE. The register block
        and the downsample count share the TRNG reset; the clean start writes N_r and
        the bypass before the boot gate passes any strobe, so the count of selected
        outputs starts at the first gated strobe. Anchor: ``esrc_stream_valid_gated_o``
        and ``esrc_compress_vld_o``; the clean start is the only stimulus.

        The control needs the CTRL readback and a trace where a count of every strobe
        from the TRNG release or from the enable write would push on another strobe
        (``_first_push_tells``). The leg repeats the clean start, up to FIRST_PUSH_TRIES
        times, with the next rate that the u0 and u_at_ctrl of the last try would tell
        (``_next_telling_rate``), until the trace tells the count start.
        """
        n = trace["n"]
        k = trace["k"]
        expect = n + 1
        fields = {
            "n": n,
            "first_push_gated": "none" if k is None else k,
            "expect": expect,
            "gated_at_ctrl": trace["gated_at_ctrl"],
            "pre_push": trace["pre_push"],
            "ds_count": "none" if trace["ds_count"] is None else trace["ds_count"],
        }
        if trace["reason"]:
            fields["reason"] = trace["reason"]
        ctrl_rb = await self._rd(ESRC_CTRL)
        bypass_rb = _get(ctrl_rb, "CTRL", "BYPASS_ENTROPY_COMPRESSOR")
        rate_rb = _get(ctrl_rb, "CTRL", "DOWNSAMPLE_RATE")
        self.chk.ctrl(
            "COND-FIRST-PUSH",
            trace["gated_at_ctrl"] == 0
            and trace["pre_push"] == 0
            and bypass_rb == 1
            and rate_rb == n
            and _first_push_tells(trace),
            gated_at_ctrl=trace["gated_at_ctrl"],
            pre_push=trace["pre_push"],
            n=n,
            bypass_rb=bypass_rb,
            rate_rb=rate_rb,
            u0="none" if trace["u0"] is None else trace["u0"],
            u_at_ctrl=trace["u_at_ctrl"],
            tries=trace["tries"],
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
        """Lanes off, SAMPLE_CLK_DIV = ``div``, then the lane enable under the trace.

        ``held`` is the set of counts that a divider which keeps its count while
        disabled would hold, from ``esrc_decor_div_lane0_o`` on every clock from the
        disable write to the end of the ``div`` write: the count on the clock before
        the last run of zeros, and also 0 when that count is the stored value (the run
        can then start at a wrap); {0} when every count is 0; None when the trace does
        not end in zeros.
        """
        dut = cocotb.top
        st = {
            "e0": None,
            "pre": 0,
            "div_tap": None,
            "held": None,
            "strobes": [],
            "reason": "",
        }
        stored = _get(await self._rd(ESRC_DECORRELATOR_CTRL), "DECORRELATOR_CTRL", "SAMPLE_CLK_DIV")
        counts: list[int] = []
        run = [True]

        async def _div_trace() -> None:
            while run[0]:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                counts.append(self.rd(dut.esrc_decor_div_lane0_o))
            await NextTimeStep()

        trace = cocotb.start_soon(_div_trace())
        off = await self._lanes_off()
        await self._wr(
            ESRC_DECORRELATOR_CTRL, _val("DECORRELATOR_CTRL", BYPASS=BYPASS_ALL, SAMPLE_CLK_DIV=div)
        )
        run[0] = False
        await trace
        z = len(counts)
        while z and counts[z - 1] == 0:
            z -= 1
        if z == 0 and counts:
            st["held"] = {0}
        elif z < len(counts):
            st["held"] = {counts[z - 1], 0} if counts[z - 1] == stored else {counts[z - 1]}
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
        so a value written before the enable sets the first distance. Any fixed
        delay L from the ``esrc_ro_enable_o`` tap to the lane enable is the same for
        every value, so the offset first distance - steady gap is equal for D_ref,
        0 and D_r; CHK-COND-FIRST-STROBE grades the offsets of 0 and D_r against
        the offset of D_ref, with no time base and no assumed L. A divider that
        keeps its count k while disabled gives the offset L - min(k, D), so the
        control CTRL-COND-FIRST-STROBE needs min(k, D) of the graded value to
        differ from that of D_ref for every k in ``held`` (see ``_walk_one``). That
        control cannot hold for 0 when the ``held`` of D_ref contains 0, so the walk of
        D_ref repeats, REF_WALK_SHIFT_CLKS clocks later each time, up to REF_WALK_TRIES
        times until its ``held`` has no 0. The enable of a lane is
        RING_OSC_ENABLE.ENABLE (entropy_source.adoc:357); each value is written with
        every lane disabled and then the lanes are enabled, the order of
        ``doc/programmer/src/sep-programming.adoc:409-411,427``. Anchor:
        ``esrc_ro_enable_o`` and ``esrc_decor_valid_o``.
        """
        plan = self.plan
        await self._wr(ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=0))
        ref: dict | None = None
        ratio_pass = 0
        for div in plan.div_walk:
            st = await self._walk_one(div)
            tries = 1
            while div == RESET_DIV and st["held"] and 0 in st["held"] and tries < REF_WALK_TRIES:
                await ClockCycles(cocotb.top.clk_i, REF_WALK_SHIFT_CLKS)
                st = await self._walk_one(div)
                tries += 1
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
            st["offset"] = st["first"] - st["gap"] if st["ok"] else None
            self.logger.info(
                "INFO-COND-FIRST-OFFSET seed=%d div=%d tries=%d first_clk=%s gap_clk=%s offset=%s"
                " held=%s",
                plan.seed,
                div,
                tries,
                "none" if st["first"] is None else st["first"],
                "none" if st["gap"] is None else st["gap"],
                "none" if st["offset"] is None else st["offset"],
                _held(st["held"]),
            )
            if div == RESET_DIV:
                ref = st
                continue
            ref_off = None if ref is None else ref["offset"]
            h, h_ref = st["held"], None if ref is None else ref["held"]
            self.chk.ctrl(
                "COND-FIRST-STROBE",
                h is not None
                and h_ref is not None
                and all(min(a, div) != min(b, RESET_DIV) for a in h for b in h_ref),
                div=div,
                held=_held(h),
                ref_held=_held(h_ref),
            )
            if self.chk.ok(
                "COND-FIRST-STROBE",
                st["offset"] is not None and ref_off is not None and st["offset"] == ref_off,
                div=div,
                ref_div=RESET_DIV,
                first_clk="none" if st["first"] is None else st["first"],
                gap_clk="none" if st["gap"] is None else st["gap"],
                offset="none" if st["offset"] is None else st["offset"],
                ref_offset="none" if ref_off is None else ref_off,
            ):
                await self._cnt_pass(ESRC_CNT_PASS_FIRST_STROBE)
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
        """One row per clk_i (ReadOnly): (strobe, gated strobe, FIFO word, ds count,
        div count, FIFO word data)."""
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
                    self.rd(dut.esrc_compress_data_o),
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

        await self._bypass_midgroup(rows)
        await self._wr(
            ESRC_CTRL, _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=plan.n_r)
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

    async def _bypass_midgroup(self, rows: list) -> None:
        """OBS-COND-BYPASS-MIDGROUP: compressor in use, whitening off; after a FIFO
        word and ``bypass_strobe`` gated strobes, CTRL.BYPASS_ENTROPY_COMPRESSOR is
        written 1 and then 0. Logs the FIFO words between the two write responses
        and the next three FIFO words after the second."""
        plan = self.plan
        p = RESET_DIV + 1
        bound = (plan.n_r + 6) * p * 4
        await self._wr(ESRC_CTRL, _val("CTRL", DOWNSAMPLE_RATE=plan.n_r, SHA256_WHITENING_ENABLE=0))
        push = await self._wait_row(rows, len(rows), lambda r: r[2], bound)
        strobes = []
        if push:
            strobes = await self._wait_row(
                rows, push[0] + 1, lambda r: r[1], bound, count=plan.bypass_strobe
            )
        await self._wr(
            ESRC_CTRL,
            _val("CTRL", BYPASS_ENTROPY_COMPRESSOR=1, DOWNSAMPLE_RATE=plan.n_r),
        )
        i_on = len(rows) - 1
        await self._wr(ESRC_CTRL, _val("CTRL", DOWNSAMPLE_RATE=plan.n_r, SHA256_WHITENING_ENABLE=0))
        i_off = len(rows) - 1
        nxt = await self._wait_row(rows, i_off + 1, lambda r: r[2], 3 * bound, count=3)
        between = [rows[j][5] for j in range(i_on + 1, i_off + 1) if rows[j][2]]
        fields = {
            "strobe": plan.bypass_strobe,
            "pushes_between": len(between),
            "words_between": ",".join(f"0x{w:08x}" for w in between) or "none",
            "next_words": ",".join(f"0x{rows[j][5]:08x}" for j in nxt) or "none",
            "next_gaps_clk": ",".join(str(b - a) for a, b in zip(nxt, nxt[1:])) or "none",
        }
        if not push or len(strobes) < plan.bypass_strobe or len(nxt) < 3:
            fields["reason"] = "timeout:push"
        self.chk.obs("COND-BYPASS-MIDGROUP", **fields)

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
        self.chk.info(
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
        sha_windows: list[tuple[int, int]] = []
        ok, biw_seen, _, sha_reads = await self._poll_biw(SHA_BIW_MIN, cap, white, sha_windows)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        pushes = white.pushes - push0
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))
        await white.stop()
        self._grade_sha_status_reads(white, sha_reads, sha_windows)
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
        # FIFO_CTRL.ENABLE gates the FIFO write (architecture.adoc:150): with it 0
        # since the drain, the pass-through window starts from an empty FIFO.
        reflush = _get(await self._rd(ESRC_FIFO_STATUS), "FIFO_STATUS", "LEVEL")
        self.chk.ctrl("COND-REFLUSH", reflush == 0, level=reflush)
        pass_tap = SepEsrcShaTap(self.rd).start()
        biw_map: list[tuple[int, int, int, int]] = []
        map_task = cocotb.start_soon(self._biw_map_trace(biw_map, cap))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=1))
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=1))
        p_ok, _, _, out_reads = await self._poll_biw(PASSTHRU_BIW_MIN, cap)
        await self._wr(ESRC_FIFO_CTRL, _val("FIFO_CTRL", ENABLE=0))
        await self._wr(ESRC_BIW_OBS_CTRL, _val("BIW_OBS_CTRL", RAW_ENABLE=0))
        await pass_tap.stop()
        if not map_task.done():
            map_task.cancel()
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
        self.chk.obs(
            "ESRC-BIW-MAP",
            pairs=len(biw_map),
            word=[f"0x{p[2]:08x}" for p in biw_map],
            bytes=[f"0x{p[1]:024x}" for p in biw_map],
            bytes_prev=[f"0x{p[0]:024x}" for p in biw_map],
            lag_clk=[p[3] for p in biw_map],
            in_biw_obs=[p[2] in biw_words for p in biw_map],
        )
        outs = [_get(v, "SHA256_STATUS", "OUTPUT_COUNT") for v in out_reads]
        nonzero = sum(1 for o in outs if o)
        self.chk.obs(
            "COND-PASSTHRU-OUTCOUNT",
            reads=len(outs),
            nonzero=nonzero,
            values=",".join(str(v) for v in sorted(set(outs))) or "none",
            busy_zero=busy_ok,
        )

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

    def _grade_sha_status_reads(
        self, tap: SepEsrcShaTap, reads: list[int], windows: list[tuple[int, int]]
    ) -> None:
        """CHK-COND-SHA-STATUS-READS: the polled SHA256_STATUS reads of the whitened
        window against the field meanings, counted from the first block boundary.

        The anchor is the first clock after the first quiet tap clock q0 where BUSY
        rises: a digest is then in processing (entropy_source.rdl:78), so the 16 words
        of one block (architecture.adoc:142) are complete and the open input block
        holds 0 words. The words in the open block at clock c are 16 plus the input
        words from the anchor to c (negative before the anchor). The INPUT_COUNT that
        the tap reads at q0 is graded against that count too.

        A read samples the register on a clock of its bus window ``[start - 1, end]``.
        Only a read with no input or FIFO word within ``QUIET_GUARD`` clocks of that
        window is graded, so the expected fields hold on every clock it can sample.
        With no backpressure on the FIFO words (architecture.adoc:148) no graded read
        falls inside the output of a digest, so each graded read expects
        OUTPUT_COUNT = 0 (or 0 or 8 before a digest gives its first word). The control
        logs the graded reads that expect a non-zero OUTPUT_COUNT."""
        tr = tap.trace
        quiet = tap.quiet_clocks()
        graded = busy_graded = in_graded = out_graded = 0
        errors: list[str] = []
        q0 = quiet[0] if quiet else None
        a = None
        if q0 is not None:
            a = next((c for c in range(q0 + 1, len(tr)) if tr[c][0] and not tr[c - 1][0]), None)
        want_q0 = "none"
        if a is not None:
            want_q0 = BLOCK_WORDS - (tr[a][3] - tr[q0][3])
            if tr[q0][2] != want_q0:
                errors.append(f"q0:in={tr[q0][2]}/{want_q0}")
        for value, (start, end) in zip(reads, windows):
            lo, hi = start - 1 - QUIET_GUARD, end + QUIET_GUARD
            if a is None or lo <= q0 or hi >= len(tr):
                continue
            if tr[hi][3] != tr[lo - 1][3] or tr[hi][4] != tr[lo - 1][4]:
                continue
            n = BLOCK_WORDS + tr[hi][3] - tr[a][3]
            pending = DIGEST_WORDS * (n // BLOCK_WORDS) - (tr[hi][4] - tr[a][4])
            want_in = n % BLOCK_WORDS
            want_busy = int(pending > 0)
            if pending <= 0:
                want_out: tuple[int, ...] = (0,)
            elif pending % DIGEST_WORDS:
                want_out = (pending % DIGEST_WORDS,)
            else:
                want_out = (0, DIGEST_WORDS)
            busy = _get(value, "SHA256_STATUS", "BUSY")
            got_in = _get(value, "SHA256_STATUS", "INPUT_COUNT")
            got_out = _get(value, "SHA256_STATUS", "OUTPUT_COUNT")
            graded += 1
            busy_graded += want_busy
            in_graded += int(want_in != 0)
            out_graded += int(0 not in want_out)
            if (
                n < 0
                or pending < 0
                or busy != want_busy
                or got_in != want_in
                or got_out not in want_out
            ):
                errors.append(
                    f"read{graded}=0x{value:x}:busy={busy}/{want_busy},"
                    f"in={got_in}/{want_in},out={got_out}/{'|'.join(map(str, want_out))},"
                    f"pending={pending}"
                )
        self.chk.ctrl(
            "COND-SHA-STATUS-READS",
            busy_graded >= 1 and in_graded >= 1,
            reads=len(reads),
            graded=graded,
            busy_graded=busy_graded,
            in_nonzero_graded=in_graded,
            out_nonzero_graded=out_graded,
            quiet_clock="none" if q0 is None else q0,
            anchor_clock="none" if a is None else a,
        )
        self.chk.ok(
            "COND-SHA-STATUS-READS",
            graded > 0 and not errors,
            reads=len(reads),
            graded=graded,
            input_count_q0="none" if q0 is None else tr[q0][2],
            expected_input_count_q0=want_q0,
            mismatches=len(errors),
            first_errors=errors[:4],
            values=[f"0x{v:x}" for v in reads],
        )

    async def _biw_map_trace(self, pairs: list, bound: int) -> None:
        """The first BIW_MAP_WORDS words of ``esrc_compress_vld_o`` with their strobe bytes.

        On every ``clk_i`` (ReadOnly) a strobe of ``esrc_decor_valid_o`` records
        ``esrc_decor_bytes_o``; a word appends (bytes of the strobe before the last,
        bytes of the last strobe, ``esrc_compress_data_o``, clocks from the last strobe).
        A strobe and a word on one clock: the strobe first. Words before the second
        strobe are not paired.
        """
        dut = cocotb.top
        prev = last = None
        last_clk = 0
        for clk in range(bound):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.esrc_decor_valid_o):
                prev, last, last_clk = last, self.rd(dut.esrc_decor_bytes_o), clk
            if self.rd(dut.esrc_compress_vld_o) and prev is not None:
                pairs.append((prev, last, self.rd(dut.esrc_compress_data_o), clk - last_clk))
                if len(pairs) == BIW_MAP_WORDS:
                    break
        await NextTimeStep()

    async def _poll_biw(
        self,
        minimum: int,
        bound: int,
        tap: SepEsrcShaTap | None = None,
        windows: list[tuple[int, int]] | None = None,
    ):
        """Poll BIW_OBS_STATUS.LEVEL >= minimum; reads SHA256_STATUS after each poll.

        With ``tap`` and ``windows``, each SHA256_STATUS read appends the tap trace
        lengths before the request and after the response: its bus window."""
        t0 = self._now()
        sha: list[int] = []
        level = 0
        for _ in range(bound + 1):
            level = _get(await self._rd(ESRC_BIW_OBS_STATUS), "BIW_OBS_STATUS", "LEVEL")
            start = len(tap.trace) if tap is not None else 0
            sha.append(await self._rd(ESRC_SHA256_STATUS))
            if tap is not None and windows is not None:
                windows.append((start, len(tap.trace)))
            if level >= minimum:
                return True, level, self._now() - t0, sha
            if self._now() - t0 > bound:
                break
        return False, level, self._now() - t0, sha
