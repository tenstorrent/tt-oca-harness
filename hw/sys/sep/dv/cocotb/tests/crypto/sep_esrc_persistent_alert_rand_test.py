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
  * The TRNG reset is a full-IP reset (``architecture.adoc:227``), so
    ``ALERT_THRESHOLD`` reads its reset value after it.
  * ``MAIN_SM_STATUS.ERR`` (``entropy_source.adoc:410``, RW1C, reset 0x0)
    latches a health-test counter integrity error and clears on a reset of the
    block (``architecture.adoc:136``).
    ``INTR_STATUS.PERSISTENT_FAILURE`` (``entropy_source.adoc:140``, reset 0x0)
    also indicates a health-test counter error.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20: the TRNG is released, the
Key Manager and every crypto engine are held. The noise model drives
``balanced`` on all 12 lanes from before the first TRNG reset release; a burst
drives ``stuck0`` on all lanes for whole windows (W strobes of
``esrc_decor_valid_o``), then the four break words (``BREAK``), then
``balanced`` again. Every ESRC start is a clean start of the window W.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the trip thresholds, 3 and a drawn T_d (4, 5 or 7), or in shard 3
both 5 and 7 (drawn without replacement, so every shard-3 seed trips at 5 and at
7); the order of the blocks, with the threshold 0 after at least one trip block;
the window of each threshold (256 or 512), the clean gap of the
consecutive leg (2, 3 or 4 windows), the order of the two trips of each
threshold, the masks and the permutation of ``balanced``, and the two counter
bits of the ERR leg (two different bits of the 32-bit counter copy), and the
illegal main-state encoding of the illegal-state leg.

Shards (``env/sep_shard.py``): shard 1 is the reset leg and the threshold
blocks; shard 2 is the reset leg and the ERR leg; shard 3 is the reset leg and
the threshold blocks 0, 5 and 7, with no no-trip leg, and it does not grade
CHK-PF-NOTRIP and CHK-PF-TRIP-HOLD: it logs ``OBS-BLOCKED CHK-PF-TRIP-HOLD``
at each trip, with the reason, and releases no cell by them. Shard 1 and the entry
without ``+sep_shard`` grade both. The entry without
``+sep_shard`` runs every leg, the ERR leg last.

Checkers:
  CHK-PF-RESET    ALERT_THRESHOLD reads 0x4 after a TRNG reset that follows a
                  write of 7. Control: it read 7 before the reset.
  CHK-PF-TRIP-COUNT  every trip: exactly T failing windows (an exact burst,
                  below), then clean noise. ALERT reads 1 within LAT_WINDOWS
                  windows of words from the start of window T (a wait bound,
                  not a graded latency), PF reads 1, and the peak of
                  ANY_FAIL_COUNT is at least T. Control: ALERT = PF = 0 and
                  ANY_FAIL_COUNT = 0 before the burst. Its FCOV cells are
                  released only when the peak is exactly T; otherwise the leaf
                  logs INFO-PF-TRIP-COUNT-HOLD and releases none.
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
                  of the same threshold reach the alert, the peak is non-zero,
                  and ALERT_THRESHOLD read back T after the start of the leg.
  CHK-PF-CONSEC   two bursts of T - 2 stuck windows with a clean gap: the peak
                  of ANY_FAIL_COUNT of each burst is at least T - 2, no alert
                  at any poll up to LAT_WINDOWS windows of words after the
                  second burst, and the count clears by the wrap 2W words after
                  the break words (below). A burst of n x W stuck words holds a
                  zero run above REPETITION_LIMIT = 200 for its last
                  n x W - 200 > (n - 1) x W words, so at least n windows fail
                  in it, whatever its offset to the window wraps. Control: the
                  trips of the same threshold reach the alert, and
                  ALERT_THRESHOLD read back T after the start of the leg.
  CHK-PF-DISABLE  T = 0, ten stuck windows: no alert at any poll up to
                  LAT_WINDOWS windows of words after the burst, ANY_FAIL_COUNT
                  peak > 8, and after the burst the count clears by the wrap 2W
                  words after the break words (below).
                  Control: every trip of the blocks that ran before it reaches
                  the alert.
  CHK-PF-HALT     after a trip, BUSY = 0 and a drain: LEVEL stays 0 and
                  ``esrc_compress_vld_o`` is silent for H = t_ref. Control: the
                  clean run shows 24 stream strobes in t_ref.
  CHK-SM-ERR      the last leg, after a TRNG reset. ``leg=set``: ERR reads 0,
                  then the counter-copy inject (``esrc_cntr_inject_i``: one
                  copy of the ``REPCNT_TOTAL_FAILS`` counter differs from the
                  other in one drawn bit, ``docs/SEP_TB_ARCH.adoc``), a wait of
                  SM_ERR_WAIT_CLKS clocks, and ONE read: ERR reads 1. With
                  INTR_ENABLE written to all ones before the leg,
                  PERSISTENT_FAILURE reads 0 before the inject and 1 after it.
                  ``leg=reset_clears``: a second inject in the other drawn
                  bit, ERR reads 1, a TRNG reset (the inject drops before the
                  release), and ERR reads 0 and PERSISTENT_FAILURE reads 0.
                  Each line grades the whole ERR field (and the
                  PERSISTENT_FAILURE field where named); the read words are
                  logged.
  OBS-SM-ERR-W0   the inject is dropped (the copies stay apart), a write of 0
                  to MAIN_SM_STATUS, then ERR at the next read. Logged, not
                  graded: the integrity error persists, so ERR latches again
                  whatever the write did, and only a reset ends the error (which
                  also clears ERR). No state with ERR 1 and the cause gone
                  exists in which a write of 0 could fail.
  OBS-SM-ERR-W1C  a write of 1 to ERR while the integrity error persists, then
                  ERR at the next read. Logged, not graded: no text states
                  whether a write of 1 clears ERR while its cause persists.
                  Both OBS writes run with the coverage window closed.
  OBS-SM-ILLEGAL  VCS only, after the ERR leg: ERR reads 0 (control
                  CTRL-SM-ILLEGAL), then the leaf forces a drawn encoding
                  outside the state set of the main state machine design
                  package on its state flops for 2 clocks and releases it; after
                  SM_ERR_WAIT_CLKS clocks ERR is logged. Logged, not graded: no
                  .adoc or RDL lists the legal encodings of MAIN_SM_STATUS.STATE,
                  so no specification makes the forced value an illegal state.
                  Under Verilator the state flops are not public and the leg
                  logs ``INFO-SM-ILLEGAL-SKIP``.
  OBS-SM-ILLEGAL-PF  INTR_STATUS.PERSISTENT_FAILURE after the illegal state.
                  Logged, not graded: the RDL names a health-test failure or a
                  counter error for it, not an illegal state.
  CHK-PIC16       every trip that ends by a MODULE_ENABLE cycle, once ALERT
                  reads 1: vector bit 15 of ``sep_internal_interrupts_probe_o``
                  (PIC source 16, the entropy-source interrupt;
                  ``hw/sys/sep/doc/interrupts.adoc:23``, ``:109-111``) reads 1,
                  with INTR_ENABLE.PERSISTENT_FAILURE set by the clean start
                  (``entropy_source.adoc:164``). Control: PERSISTENT_FAILURE
                  read 1 (CTRL-PIC16).
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
Every stuck word extends the zero run of every lane, so the run is above
REPETITION_LIMIT = 200 from word 201 (``entropy_source.adoc`` REPETITION_LIMIT:
the test fails above the limit; ``architecture.adoc:124``). The window that holds
word 201 fails and ends at or before word 200 + W; each later stuck window fails
too (its run stays above the limit, and its lanes hold 0 ones, under the APT low
limit W/4). So the wrap that ends failing window n - 1 comes at or before word
(n - 1) x W + 200, and a read issued more than one word after it reads n - 1.
The three checks fail with ``reason=late:count_<n - 1>`` when the last read that
read below n - 1 was issued after word (n - 1) x W + 201 (``last_below_issue``,
``expect_last_below_issue_max``). The word is taken at the issue of the read, so
the read latency is outside the bound. A DUT that drops one failing window
reads n - 1 one wrap later and fails this bound when the first failing window
ends after word 201.
Stuck0 stays until word o + W - W/8, then the break words and balanced. Window
n holds at least 7W/8 >= 224 stuck words, a zero run above REPETITION_LIMIT =
200 inside the window alone, so it fails. The break words end every
stream-bit zero run W/8 - 4 >= 28 words before the next wrap, so the next
window holds clean noise only and no health test fails in it. The leaf logs
the sum of the ``*_TOTAL_FAILS`` counters after the wrap that ends window n
minus the sum at that wrap (``test_fails_after_window_n``), the DUT record
that the later windows hold no failure. Before the consecutive leg and before
the first trip of a block, a leg that left ALERT, PF or ANY_FAIL_COUNT set is
followed by a restart (``INFO-PF-LEG-RESTART``). CHK-PF-TRIP-HOLD and
CHK-PF-NOTRIP grade the peak of ANY_FAIL_COUNT as exactly n, so a misplaced
switch fails a check and never passes one.

Coverage: each leg runs in its own graded window. Every cell that this leaf
fills from a DUT event is held by the sampler and released by the pass label
``esrc_pa_pass`` (``set_esrc_pa_pass``), which the leaf writes only after the
check that grades that leg passes; a FAIL closes the window. A check releases
nothing when a control was logged absent since the previous grade, or when its
own control (``CTRL-<check>``) is not logged as seen just before it. The trips
of a block run before its no-trip and consecutive legs, and the threshold 0 runs
after a trip block, so the controls of CHK-PF-NOTRIP, CHK-PF-CONSEC and
CHK-PF-DISABLE are logged before those checks are graded. CHK-PF-TRIP-HOLD
is graded at the end of its trip: its values are taken before the halt and exit
legs, which it does not grade. The ``cp_sm_err`` cells set and reset_clears are
held and released by ``ESRC_PA_SM_ERR`` after the CHK-SM-ERR line of that leg
passes; the two OBS writes of the ERR leg run with the window closed.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.handle import Force, Release
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
    ESRC_PA_CONSEC,
    ESRC_PA_DISABLE,
    ESRC_PA_HALT,
    ESRC_PA_NOTRIP,
    ESRC_PA_RECOVER_E,
    ESRC_PA_RECOVER_R,
    ESRC_PA_RESET,
    ESRC_PA_SM_ERR,
    ESRC_PA_TRIP_COUNT,
    close_graded_window,
    open_graded_window,
    set_esrc_af_clear_bound,
    set_esrc_pa_pass,
)
from env.sep_seeded_rng import SepSeededRng
from env.sep_shard import sep_shard
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
    CLEAN_REPETITION_LIMIT,
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
# Shard 3 runs both of these trip thresholds, in a drawn order, in place of 3 and
# T_d: the green shard then trips at 5 and at 7 on every seed. The reset leg reads
# the 4 on every seed, and the alert test grades the trip at 3.
T_SHARD3 = (5, 7)
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
M_ERR, ERR_BP = _fm("MAIN_SM_STATUS", "ERR")
M_STATE, _ = _fm("MAIN_SM_STATUS", "STATE")
STATE_BITS = M_STATE.bit_length()
# Stimulus of an OBS leg only: the encodings of the main state machine, from
# vendor/lowRISC/opentitan/upstream/hw/ip/entropy_src/rtl/entropy_src_main_sm_pkg.sv
# (state_e). No .adoc or RDL lists them, so OBS-SM-ILLEGAL, which forces a value
# outside this set, grades nothing.
MAIN_SM_ENCODINGS = frozenset(
    (
        0b011110101, 0b111010010, 0b101101110, 0b010001110, 0b000101100,
        0b100000001, 0b110100101, 0b000010111, 0b001000000, 0b110100010,
        0b011000011, 0b001011001, 0b100001111, 0b011111000, 0b010111111,
        0b110011000, 0b111001101, 0b111111011, 0b001110011,
    )
)  # fmt: skip
# The main state machine under SEP_ESRC (tb/tb_top.sv). The illegal-state leg
# forces the state flop of u_state_regs and, where it exists, the state_q flop
# that PRIM_FLOP_SPARSE_FSM adds beside it under SIMULATION, with one value, so
# the two stay equal; both are variables and keep the value after the release
# until the next clock edge loads the next state into both.
MAIN_SM_PATH = "u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_main_sm"
MAIN_SM_FLOPS = ("u_state_regs.u_state_flop.q_o", "state_q")
# Clocks the illegal value is held on the state flop output.
ILLEGAL_HOLD_CLKS = 2
# Bits of the counter copy that the inject can flip: REPCNT_TOTAL_FAILS.FAIL_COUNT
# is 32 bits (entropy_source.adoc:682).
CNTR_BITS = ENTROPY_SOURCE.mask("REPCNT_TOTAL_FAILS").bit_length()
# A write with no bit set: a write of 0 to ERR (and to ALERT).
SM_W0 = 0
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
# Clocks from the inject rise to the one graded ERR read. A wait bound: no text
# states the latch latency, and a later latch fails CHK-SM-ERR leg=set.
SM_ERR_WAIT_CLKS = 64
# Clocks the leaf holds a bit of esrc_pa_pass before it writes 0.
PA_HOLD_CLKS = 2

# Shards (env/sep_shard.py). Shard 1: the reset leg and the threshold blocks.
# Shard 2: the reset leg and the ERR leg, which no ANY_FAIL_COUNT grade touches.
# Shard 3: the reset leg and the blocks 0, 5 and 7, without the no-trip leg and
# without the CHK-PF-TRIP-HOLD grade.
SHARD_EVIDENCE = {
    1: (
        "CHK-PF-RESET",
        "CHK-PF-TRIP-COUNT",
        "CHK-PF-TRIP-HOLD",
        "CHK-PF-NOTRIP",
        "CHK-PF-CONSEC",
        "CHK-PF-DISABLE",
        "CHK-PF-HALT",
        "CHK-PF-RECOVER",
        "CHK-PIC16",
    ),
    2: ("CHK-PF-RESET", "CHK-SM-ERR"),
    3: (
        "CHK-PF-RESET",
        "CHK-PF-TRIP-COUNT",
        "CHK-PF-CONSEC",
        "CHK-PF-DISABLE",
        "CHK-PF-HALT",
        "CHK-PF-RECOVER",
        "CHK-PIC16",
    ),
}
# Checks that shard 3 does not grade: it runs no no-trip leg, and it logs the
# CHK-PF-TRIP-HOLD values as an INFO line.
SHARD3_UNGRADED = ("PF-NOTRIP", "PF-TRIP-HOLD")
# Checks whose pass bit releases cells only when the control of the same check
# was logged as seen just before the grade (``_grade``).
CTRL_GATED = ("PF-RESET", "PF-TRIP-COUNT", "PF-NOTRIP", "PF-CONSEC", "PF-DISABLE", "PF-RECOVER")

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
    trip_thr: tuple[int, ...]
    order: tuple[int, ...]
    window: dict[int, int]
    gap: dict[int, int]
    trips: dict[int, tuple[str, str]]
    balanced: tuple[Balanced, ...]
    inj_bits: tuple[int, int]
    illegal_state: int

    def describe(self) -> str:
        blocks = " ".join(
            f"T{t}:win={self.window[t]}"
            + (f",gap={self.gap[t]},trips={'+'.join(self.trips[t])}" if t else "")
            for t in self.order
        )
        return (
            f"trip_thr={','.join(str(t) for t in self.trip_thr)} order={','.join(str(t) for t in self.order)} {blocks} "
            f"{describe(self.balanced)} inj_bits={self.inj_bits[0]},{self.inj_bits[1]} "
            f"illegal_state=0x{self.illegal_state:03x}"
        )


def draw_plan(seed: int, shard: int | None = None) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access.

    The trip thresholds are 3 and T_d (drawn from T_DRAWN), or in shard 3 the two
    values of T_SHARD3 (drawn without replacement, so only their order is drawn).
    The threshold 0 runs after at least one trip block: the trips of the blocks
    before it are the control of CHK-PF-DISABLE.
    """
    rng = SepSeededRng(seed)
    if shard == 3:
        trip_thr = list(T_SHARD3)
    else:
        trip_thr = [3, rng.choice(T_DRAWN)]
    rng.shuffle(trip_thr)
    pos = rng.choice(range(1, len(trip_thr) + 1))
    order = trip_thr[:pos] + [0] + trip_thr[pos:]
    window: dict[int, int] = {}
    gap: dict[int, int] = {}
    trips: dict[int, tuple[str, str]] = {}
    for t in (0, *sorted(trip_thr)):
        window[t] = rng.choice(WINDOWS)
        if t:
            gap[t] = rng.choice(GAPS)
            tr = ["E", "R"]
            rng.shuffle(tr)
            trips[t] = (tr[0], tr[1])
    balanced = tuple(balanced_lanes(rng))
    bit_a = rng.choice(range(CNTR_BITS))
    bit_b = rng.choice([b for b in range(CNTR_BITS) if b != bit_a])
    illegal = rng.choice([v for v in range(1 << STATE_BITS) if v not in MAIN_SM_ENCODINGS])
    return Plan(
        seed, tuple(trip_thr), tuple(order), window, gap, trips, balanced, (bit_a, bit_b), illegal
    )


def _handle(path: str):
    """The simulator handle at a dotted path below the tb top, or None."""
    node = cocotb.top
    for part in path.split("."):
        node = getattr(node, part, None)
        if node is None:
            return None
    return node


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
    notrip_thr: int | None = None  # ALERT_THRESHOLD readback before the no-trip burst
    consec_thr: int | None = None  # ALERT_THRESHOLD readback before the consecutive bursts


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
        "CHK-PIC16",
        "CHK-SM-ERR",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        shard = sep_shard(self, SHARD_EVIDENCE)
        await self.bring_up_no_cpu(park=BASELINE_PARK)
        seed = self.random_seed()
        plan = draw_plan(seed, shard)
        self.logger.info("INFO-PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.logger.info("INFO-BASELINE sw_reset_n=0x%02x", self.swrst.value)
        self.esrc = _Esrc(self)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        self.noise.start(list(plan.balanced))
        self.vld: SepBitWatch | None = None
        self.p: int | None = None
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)
        self.stream_clean: int | None = None
        # Per trip block that has run: the alert of each of its trips (control of
        # CHK-PF-DISABLE).
        self.block_trips: dict[int, list[int]] = {}
        # Control of each check, logged just before its grade; popped by _grade.
        self.ctrl_seen: dict[str, bool] = {}
        # A control that was logged absent since the last grade.
        self.ctrl_absent = False
        self.disable_result: dict | None = None
        self.started = False
        self.thr_rb: int | None = None
        self.trip_graded = False
        self.trip_hold: dict | None = None
        self.ungraded = SHARD3_UNGRADED if shard == 3 else ()
        self.run_notrip = shard != 3

        await self._reset_value_leg()
        if shard != 2:
            for thr in plan.order:
                if thr == 0:
                    await self._block_disable()
                else:
                    await self._block_trip(thr)
            close_graded_window(self.logger)
        if shard not in (1, 3):
            await self._sm_err_leg()
            await self._sm_illegal_leg()
        close_graded_window(self.logger)

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

    async def _release(self, bits: int) -> None:
        """Pulse the pass bits of a check that passed (esrc_pa_pass, PA_HOLD_CLKS)."""
        if set_esrc_pa_pass(bits, self.logger):
            for _ in range(PA_HOLD_CLKS):
                await RisingEdge(cocotb.top.clk_i)
            set_esrc_pa_pass(0, self.logger)
            await RisingEdge(cocotb.top.clk_i)

    def _ctrl(self, name: str, cond: bool, **fields) -> bool:
        """Log one control; ``_grade`` of the same check reads the result."""
        seen = self.chk.ctrl(name, cond, **fields)
        self.ctrl_seen[name] = seen
        if not seen:
            self.ctrl_absent = True
        return seen

    async def _grade(self, name: str, cond: bool, bits: int, **fields) -> bool:
        """Grade one check; a FAIL closes the window first, a PASS releases ``bits``.

        A PASS releases nothing, and closes the window, when a control was logged
        absent since the last grade, or when the check is in CTRL_GATED and its own
        control was not logged as seen just before this grade.
        """
        ctrl = self.ctrl_seen.pop(name, None)
        held = self.ctrl_absent or (name in CTRL_GATED and ctrl is not True)
        self.ctrl_absent = False
        if not cond:
            close_graded_window(self.logger)
            return self.chk.ok(name, False, **fields)
        self.chk.ok(name, True, **fields)
        if held:
            close_graded_window(self.logger)
            self.logger.info("FCOV-ESRC-PA-HOLD %s: a control is absent, no cell released", name)
            return True
        if bits:
            await self._release(bits)
        return True

    def _fail(self, name: str, **fields) -> None:
        """A check that cannot be graded (a timeout): the check fails, then the window closes."""
        self.chk.ok(name, False, **fields)
        close_graded_window(self.logger)

    def _pic16(self) -> int:
        v = self.rd(cocotb.top.sep_internal_interrupts_probe_o, allow_unknown=True)
        return (v >> 15) & 1

    async def _grade_pic16(self, thr: int, pf: int) -> None:
        """CHK-PIC16 after a trip: vector bit 15 (PIC source 16) reads 1.

        PIC source 16 is the entropy-source interrupt on vector bit 15
        (interrupts.adoc:23, :109-111), and INTR_ENABLE.PERSISTENT_FAILURE, set by
        the clean start, enables the persistent-failure interrupt
        (entropy_source.adoc:18, :164). Control: PERSISTENT_FAILURE read 1.
        """
        pic = self._pic16()
        self._ctrl("PIC16", pf == 1, thr=thr, pf=pf)
        await self._grade("PIC16", pic == 1, 0, thr=thr, value=pic, expect_value=1)

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
            self.logger.info(
                "INFO-START-TIMEOUT %s: BOOT_PHASE_DONE not 1 bound=%d", what, self._boot_bound(win)
            )
            return False, False
        bound = self._latency_bound() if self.stream_clean else self._clocks(STREAM_CAP_STROBES)
        level, _ = await self._poll_level_gt0(bound)
        if not level:
            self.logger.info(
                "INFO-START-TIMEOUT %s: FIFO_STATUS.LEVEL stayed 0 bound=%d", what, bound
            )
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
        self.thr_rb = (await self._rd(ESRC_ALERT_THRESHOLD)) & M_THR
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
            self._ctrl(
                "PF-STREAM", False, strobes_lt=STREAM_STROBES, reason="timeout:stream", bound=bound
            )
            return None
        t_ref = box[0]
        if self.stream_clean is None:
            self.stream_clean = t_ref
        self.logger.info("INFO-T-REF t_ref=%d clk_i (24 stream strobes) bound=%d", t_ref, bound)
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
                self.chk.info("PF-BREAK", strobes=0, bound=bound)
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
            self.chk.info("PF-LEG-RESTART", thr=thr, leg=leg, alert=int(a), pf=int(f), any_fail=cnt)
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
        self._ctrl("NOISE-BYTES", mm1 == mm0 and c1 > c0, compared=c1 - c0, mismatched=mm1 - mm0)
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
        issue_prev = 0
        o = None
        if cnt0 != 0:
            res["reason"] = "count_not_zero_before"
        else:
            bound = self._word_bound(target * win, win)
            t0 = self._now()
            while self._now() - t0 <= bound:
                issue = poll_word()
                cnt = (await self._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)) & M_ANY
                w = poll_word()
                track(False, False, cnt)
                if cnt >= target - 1:
                    o = w
                    break
                o_prev = w
                issue_prev = issue
            if o is None:
                res["reason"] = f"timeout:count_{target - 1}"
                res["bound"] = bound
        if o is not None:
            # n - 1 failing windows need more than (n - 2) x W stuck words (module
            # docstring), so a read of n - 1 at or before that word is an early count.
            early_max = (target - 2) * win
            # Failing window n - 1 ends at or before word (n - 1) x W + REPETITION_LIMIT
            # (module docstring), so a read issued more than one word after it that
            # still reads below n - 1 is a late count.
            late_max = (target - 1) * win + CLEAN_REPETITION_LIMIT + 1
            res.update(
                wrap_obs=[o_prev, o],
                expect_wrap_word_gt=early_max,
                last_below_issue=issue_prev,
                expect_last_below_issue_max=late_max,
            )
            if o <= early_max:
                res["reason"] = f"early:count_{target - 1}"
            elif issue_prev > late_max:
                res["reason"] = f"late:count_{target - 1}"
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
        self._ctrl("NOISE-BYTES", mm1 == mm0 and c1 > c0, compared=c1 - c0, mismatched=mm1 - mm0)
        return res

    async def _trip(self, thr: int, win: int) -> dict:
        """An exact burst of T failing windows; grades TRIP-COUNT and TRIP-HOLD."""
        self.trip_graded = True
        r = await self._exact_burst(win, thr, trip=True)
        reason = {"reason": r["reason"]} if r["reason"] else {}
        self._ctrl(
            "PF-TRIP-COUNT",
            r["alert_before"] == 0 and r["pf_before"] == 0 and r["count_before"] == 0,
            thr=thr,
            alert_before=r["alert_before"],
            pf_before=r["pf_before"],
            count_before=r["count_before"],
        )
        # The cells of the trip are released only when the peak is exactly T, the
        # count of the failing windows (architecture.adoc:136); the check itself
        # grades the trip and a peak of at least T.
        exact = r["peak"] == thr
        if not exact:
            self.chk.info("PF-TRIP-COUNT-HOLD", thr=thr, any_fail_peak=r["peak"], released=0)
        await self._grade(
            "PF-TRIP-COUNT",
            r["reason"] is None and r["peak"] >= thr and r["alert_any"] and r["pf_final"],
            ESRC_PA_TRIP_COUNT if exact else 0,
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
            last_below_issue=r.get("last_below_issue"),
            expect_last_below_issue_max=r.get("expect_last_below_issue_max"),
            alert_bound_windows=LAT_WINDOWS,
        )
        o = r["o"]
        rel_final = None if o is None else r["final_word"] - (o + win)
        hold_min = win + win // TAIL_DIV
        # Graded at the end of the trip (_flush_trip_hold): the values are taken
        # here, before the halt and exit legs, which this check does not grade.
        self.trip_hold = {
            "ctrl": r["clean_words"] >= hold_min,
            "ctrl_fields": {
                "thr": thr,
                "clean_words": r["clean_words"],
                "expect_clean_words_min": hold_min,
            },
            "cond": r["reason"] is None and r["alert_final"] and r["pf_final"] and r["peak"] == thr,
            "fields": {
                **reason,
                "thr": thr,
                "win": win,
                "read_word_after_window_t": rel_final,
                "alert_after_clean": r["alert_final"],
                "pf_after_clean": r["pf_final"],
                "any_fail_peak": r["peak"],
                "expect_any_fail_peak": thr,
                "any_fail_final": r["count_final"],
                "test_fails_after_window_t": r.get("test_fails_after_window_n"),
            },
        }
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

    def _not_graded(self, name: str) -> bool:
        """In shard 3, log an ungraded check as OBS-BLOCKED and return True."""
        if name not in self.ungraded:
            return False
        self.chk.blocked(
            name, "shard 3 does not grade it; shard 1 and the entry without +sep_shard grade it"
        )
        return True

    def _flush_trip_hold(self) -> None:
        """Grade the CHK-PF-TRIP-HOLD values that the last trip took."""
        th = self.trip_hold
        self.trip_hold = None
        if th is None:
            return
        if self._not_graded("PF-TRIP-HOLD"):
            return
        self.chk.ctrl("PF-TRIP-HOLD", th["ctrl"], **th["ctrl_fields"])
        self.chk.ok("PF-TRIP-HOLD", th["cond"], **th["fields"])
        if not th["cond"]:
            close_graded_window(self.logger)

    # --- legs --------------------------------------------------------------------------
    async def _reset_value_leg(self) -> None:
        close_graded_window(self.logger)
        await self._trng_reset()
        await self._wr(ESRC_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=7))
        before = await self._rd(ESRC_ALERT_THRESHOLD)
        self._ctrl("PF-RESET", before & THR_FIELDS == 7, before=f"0x{before & THR_FIELDS:x}")
        try:
            await self._trng_reset()
        except TrialTimeout as exc:
            self._fail("PF-RESET", reason=f"timeout:{exc.what}", bound=exc.bound)
            return
        # The graded window opens after the reset: the stored 7 of the control write
        # is never sampled; the stored-value sample and this read see the reset value.
        open_graded_window(TEST, self.logger)
        after = await self._rd(ESRC_ALERT_THRESHOLD)
        close_graded_window(self.logger)
        await self._grade(
            "PF-RESET",
            after & THR_FIELDS == THR_RESET,
            ESRC_PA_RESET,
            alert_threshold=f"0x{after & THR_FIELDS:x}",
            expect=f"0x{THR_RESET:x}",
            rsvd=f"0x{after & ~THR_FIELDS & 0xFFFF_FFFF:x}",
            ctrl_before=f"0x{before & THR_FIELDS:x}",
        )

    async def _block_trip(self, thr: int) -> None:
        """Trips first, then the no-trip and consecutive legs.

        The trips are the controls of CHK-PF-NOTRIP and CHK-PF-CONSEC, so each of
        those controls is logged before its check is graded, and a check releases
        its cells only after its control is seen (``_grade``).
        """
        plan = self.plan
        win = plan.window[thr]
        blk = _Block(thr, win)
        try:
            await self._start_seq(thr, win)
        except TrialTimeout as exc:
            blk.start_timeout = f"timeout:{exc.what} bound={exc.bound}"
            self.block_trips[thr] = [0]
            for name in ("PF-TRIP-COUNT", "PF-TRIP-HOLD"):
                self._fail(name, thr=thr, reason=blk.start_timeout)
            await self._deny_legs(blk)
            return
        blk.t_ref = await self._measure_t_ref()
        hold = blk.t_ref

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
            self._flush_trip_hold()
            alerts.append(res["alert"])
            first = False
        blk.trip_alert = alerts
        self.block_trips[thr] = alerts

        # The trips leave the module halted, or at the reset configuration after a
        # TRNG reset: the start sequence for T and W runs again before the legs
        # that must not trip.
        try:
            await self._start_seq(thr, win)
            await self._drain()
        except TrialTimeout as exc:
            blk.start_timeout = f"timeout:{exc.what} bound={exc.bound}"
        await self._deny_legs(blk)

    async def _deny_legs(self, blk: _Block) -> None:
        """No-trip leg (not in shard 3) and consecutive leg, each control before its grade."""
        thr, win = blk.thr, blk.win
        if self.run_notrip:
            if not blk.start_timeout:
                open_graded_window(TEST, self.logger)
                blk.notrip_thr = self.thr_rb
                blk.notrip = await self._exact_burst(win, thr - 1, trip=False)
                close_graded_window(self.logger)
            self._ctrl_notrip(blk)
            await self._grade_notrip(blk)
        if not blk.start_timeout:
            n = thr - 2
            g = self.plan.gap[thr]
            first_burst = self._burst_segs(n, win, tail_words=g * win - len(BREAK))
            segs = first_burst + self._burst_segs(n, win)
            open_graded_window(TEST, self.logger)
            try:
                await self._ensure_clean(thr, win, "consec")
                blk.consec_thr = self.thr_rb
                blk.consec = await self._burst_and_settle(segs, win, split=len(first_burst))
            except TrialTimeout as exc:
                blk.consec = {"timeout": f"timeout:{exc.what} bound={exc.bound}"}
            close_graded_window(self.logger)
        self._ctrl_consec(blk)
        await self._grade_consec(blk)

    def _trip_start_timeout(self, thr: int, kind: str, exc: TrialTimeout) -> dict:
        """A trip whose set-up or wait timed out: its exit check fails with the reason."""
        reason = f"timeout:{exc.what}"
        close_graded_window(self.logger)
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
        if res["alert"]:
            await self._grade_pic16(thr, res["pf"])
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
            self._fail(
                "PF-HALT",
                thr=thr,
                sha_busy_clear=int(busy_clear),
                drained=int(drained),
                reason="timeout:busy_or_drain" if hold is not None else "no_t_ref",
            )
            level_max, vld = None, None
        else:
            level_max, vld = await self._hold(hold)
            await self._grade(
                "PF-HALT",
                level_max == 0 and vld == 0,
                ESRC_PA_HALT,
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
        self._ctrl(
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
        await self._grade(
            "PF-RECOVER",
            (not alert_c) and (not pf_c) and halted and boot and level,
            ESRC_PA_RECOVER_E,
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
        self._ctrl(
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
        await self._grade(
            "PF-RECOVER",
            (not alert_r) and (not pf_r) and boot and level,
            ESRC_PA_RECOVER_R,
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
            await self._grade_disable()
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
        await self._grade_disable()

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

    async def _grade_notrip(self, blk: _Block) -> None:
        """CHK-PF-NOTRIP at the end of the no-trip leg (its control follows the trips)."""
        nt = blk.notrip or {}
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
            "last_below_issue": nt.get("last_below_issue"),
            "expect_last_below_issue_max": nt.get("expect_last_below_issue_max"),
            "watch_words": nt.get("watch_words"),
            "expect_watch_words_min": LAT_WINDOWS * blk.win,
        }
        if blk.start_timeout:
            fields["reason"] = blk.start_timeout
        elif nt.get("reason"):
            fields["reason"] = nt["reason"]
            if nt.get("bound") is not None:
                fields["bound"] = nt["bound"]
        if self._not_graded("PF-NOTRIP"):
            return
        await self._grade(
            "PF-NOTRIP",
            not blk.start_timeout
            and nt.get("reason") is None
            and nt.get("peak") == blk.thr - 1
            and nt.get("alert_any") == 0
            and nt.get("pf_any") == 0
            and nt.get("count_final") == 0,
            ESRC_PA_NOTRIP,
            **fields,
        )

    async def _grade_consec(self, blk: _Block) -> None:
        """CHK-PF-CONSEC at the end of the consecutive leg (its control follows the trips)."""
        cs = blk.consec or {}
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
        await self._grade(
            "PF-CONSEC",
            cs.get("alert") == 0 and cs.get("pf") == 0 and cs.get("zero") and counted,
            ESRC_PA_CONSEC,
            **fields,
        )

    @staticmethod
    def _tripped(alerts: list[int] | None) -> bool:
        """Every trip of a block reached the alert."""
        return bool(alerts) and all(alerts)

    def _ctrl_notrip(self, blk: _Block) -> None:
        """Control of CHK-PF-NOTRIP: the trips of the block reach the alert."""
        tripped = self._tripped(blk.trip_alert)
        nt = blk.notrip or {}
        self._ctrl(
            "PF-NOTRIP",
            tripped and nt.get("peak", 0) > 0 and blk.notrip_thr == blk.thr,
            thr=blk.thr,
            thr_readback=blk.notrip_thr,
            ctrl_trip=int(tripped),
            any_fail_peak=nt.get("peak"),
        )

    def _ctrl_consec(self, blk: _Block) -> None:
        """Control of CHK-PF-CONSEC: the trips of the block reach the alert."""
        tripped = self._tripped(blk.trip_alert)
        # A start that timed out leaves no readback; CHK-PF-CONSEC fails on its reason.
        timed_out = bool(blk.start_timeout or (blk.consec or {}).get("timeout"))
        thr_ok = blk.consec_thr == blk.thr or (blk.consec_thr is None and timed_out)
        self._ctrl(
            "PF-CONSEC",
            tripped and thr_ok,
            thr=blk.thr,
            thr_readback=blk.consec_thr,
            ctrl_single_burst_alert=int(tripped),
        )

    async def _grade_disable(self) -> None:
        """CHK-PF-DISABLE at the end of the disable leg (its control follows the trips)."""
        self._ctrl_disable()
        d = self.disable_result or {}
        extra = {"reason": d["reason"]} if d.get("reason") else {}
        await self._grade(
            "PF-DISABLE",
            not d.get("reason")
            and d.get("alert") == 0
            and d.get("pf") == 0
            and d.get("peak", 0) > DISABLE_WINDOWS - 2
            and d.get("zero") is True,
            ESRC_PA_DISABLE,
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
        )

    def _ctrl_disable(self) -> None:
        """Control of CHK-PF-DISABLE: every trip of the blocks that ran before it reaches the alert."""
        before = sorted(self.block_trips)
        ctrl_ok = bool(before) and all(self._tripped(self.block_trips[t]) for t in before)
        self._ctrl("PF-DISABLE", ctrl_ok, ctrl_trip_thr=before, ctrl_trip_alert=int(ctrl_ok))

    # --- MAIN_SM_STATUS.ERR leg ------------------------------------------------------
    async def _sm_illegal_leg(self) -> None:
        """OBS-SM-ILLEGAL and OBS-SM-ILLEGAL-PF, after the ERR leg (VCS only).

        Logged, not graded: no .adoc or RDL lists the legal encodings of
        MAIN_SM_STATUS.STATE (entropy_source.rdl: "sparse-encoded"), so no
        specification makes the forced value an illegal state. The leaf forces the
        drawn encoding on the state flops (MAIN_SM_FLOPS) for ILLEGAL_HOLD_CLKS
        clocks, releases it, waits SM_ERR_WAIT_CLKS clocks and reads ERR once.
        Control: ERR reads 0 before the force (the ERR leg ended with a TRNG
        reset). The main state machine stays in its error state until a reset, so
        this leg is the last. Under Verilator the state flop is not public to
        cocotb and the leg is skipped (INFO-SM-ILLEGAL-SKIP).
        """
        if "verilator" in str(getattr(cocotb, "SIM_NAME", "") or "").lower():
            self.chk.info("SM-ILLEGAL-SKIP", reason="verilator: the main state flop is not public")
            return
        flops = [_handle(f"{MAIN_SM_PATH}.{f}") for f in MAIN_SM_FLOPS]
        if flops[0] is None:
            self.chk.ctrl(
                "SM-ILLEGAL", False, reason=f"no handle:{MAIN_SM_PATH}.{MAIN_SM_FLOPS[0]}"
            )
            return
        close_graded_window(self.logger)
        illegal = self.plan.illegal_state
        err0, w0 = await self._err_read()
        self.chk.ctrl("SM-ILLEGAL", err0 == 0, err_before=err0, word_before=f"0x{w0:08x}")
        flops = [h for h in flops if h is not None]
        await RisingEdge(cocotb.top.clk_i)
        for h in flops:
            h.value = Force(illegal)
        await self._clocks_wait(ILLEGAL_HOLD_CLKS)
        for h in flops:
            h.value = Release()
        await self._clocks_wait(SM_ERR_WAIT_CLKS)
        err1, w1 = await self._err_read()
        pf1 = await self._pf_read()
        self.chk.obs(
            "SM-ILLEGAL",
            state_forced=f"0x{illegal:03x}",
            flops_forced=len(flops),
            hold_clk=ILLEGAL_HOLD_CLKS,
            wait_clk=SM_ERR_WAIT_CLKS,
            err_before=err0,
            err=err1,
            word=f"0x{w1:08x}",
        )
        self.chk.obs("SM-ILLEGAL-PF", state_forced=f"0x{illegal:03x}", pf=pf1)

    async def _err_read(self) -> tuple[int, int]:
        """One MAIN_SM_STATUS read: (the ERR field, the whole word)."""
        word = await self._rd(ESRC_MAIN_SM_STATUS)
        return (word & M_ERR) >> ERR_BP, word

    async def _pf_read(self) -> int:
        """One INTR_STATUS read: the PERSISTENT_FAILURE field."""
        return int((await self._rd(ESRC_INTR_STATUS)) & M_PF != 0)

    def _inject(self, on: bool, bit: int) -> None:
        dut = cocotb.top
        dut.esrc_cntr_inject_bit_i.value = bit
        dut.esrc_cntr_inject_i.value = 1 if on else 0

    async def _clocks_wait(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_i)

    async def _sm_err_leg(self) -> None:
        """CHK-SM-ERR (set, reset_clears), OBS-SM-ERR-W0 and OBS-SM-ERR-W1C, the last leg.

        Golden: entropy_source.adoc:410 (ERR, RW1C, reset 0x0: it latches a
        health-test counter integrity error; a reset of the block clears it) and
        architecture.adoc:136 (the full entropy-source reset clears it). The main
        state machine stays in its error state until the reset, so the ERR legs
        run last.
        """
        bit_a, bit_b = self.plan.inj_bits
        close_graded_window(self.logger)
        try:
            await self._trng_reset()
        except TrialTimeout as exc:
            for leg in ("set", "reset_clears"):
                self._fail("SM-ERR", leg=leg, reason=f"timeout:{exc.what}", bound=exc.bound)
            return
        # Leg set: ERR 0 and PERSISTENT_FAILURE 0 (the probes), the inject, a wait,
        # then one read of each. A poll would pair two reads after the inject and is
        # not used. The interrupt enables are written before the window opens: no
        # text states whether a status bit latches while its enable is clear.
        await self._wr(ESRC_INTR_ENABLE, INTR_ENABLE_ALL)
        open_graded_window(TEST, self.logger)
        err0, w0 = await self._err_read()
        pf0 = await self._pf_read()
        self._inject(True, bit_a)
        await self._clocks_wait(SM_ERR_WAIT_CLKS)
        err1, w1 = await self._err_read()
        pf1 = await self._pf_read()
        await self._grade(
            "SM-ERR",
            err0 == 0 and pf0 == 0 and err1 == 1 and pf1 == 1,
            ESRC_PA_SM_ERR,
            leg="set",
            inj_bit=bit_a,
            err_before=err0,
            expect_err_before=0,
            pf_before=pf0,
            expect_pf_before=0,
            err=err1,
            expect_err=1,
            pf=pf1,
            expect_pf=1,
            wait_clk=SM_ERR_WAIT_CLKS,
            word_before=f"0x{w0:08x}",
            word=f"0x{w1:08x}",
        )
        # Write of 0, then write of 1, while the cause persists: the copies stay
        # apart after the drop, so ERR latches again whatever a write does. Both
        # are logged only, with the window closed, so no cell takes these reads.
        close_graded_window(self.logger)
        self._inject(False, bit_a)
        await self._wr(ESRC_MAIN_SM_STATUS, SM_W0)
        err2, w2 = await self._err_read()
        self.chk.obs(
            "SM-ERR-W0",
            err_before=err1,
            wr=f"0x{SM_W0:08x}",
            err=err2,
            word=f"0x{w2:08x}",
            cause="counter_copies_apart",
        )
        await self._wr(ESRC_MAIN_SM_STATUS, M_ERR)
        err3, w3 = await self._err_read()
        self.chk.obs(
            "SM-ERR-W1C",
            err_before=err2,
            wr=f"0x{M_ERR:08x}",
            err=err3,
            word=f"0x{w3:08x}",
            cause="counter_copies_apart",
        )
        # Leg reset_clears: a second inject in the other bit sets ERR again whatever
        # the write of 1 did; then the TRNG reset (the inject drops before the
        # release) and one read.
        self._inject(True, bit_b)
        await self._clocks_wait(SM_ERR_WAIT_CLKS)
        open_graded_window(TEST, self.logger)
        err4, w4 = await self._err_read()
        reset_seen = 0
        try:
            await self.setup.trng_reset(before_release=lambda: self._inject(False, bit_b))
            reset_seen = 1
        except TrialTimeout as exc:
            self._inject(False, bit_b)
            self._fail("SM-ERR", leg="reset_clears", reason=f"timeout:{exc.what}", bound=exc.bound)
            return
        err5, w5 = await self._err_read()
        pf5 = await self._pf_read()
        await self._grade(
            "SM-ERR",
            err4 == 1 and reset_seen == 1 and err5 == 0 and pf5 == 0,
            ESRC_PA_SM_ERR,
            leg="reset_clears",
            inj_bit=bit_b,
            err_before_reset=err4,
            expect_err_before_reset=1,
            trng_reset_seen=reset_seen,
            err=err5,
            expect_err=0,
            pf=pf5,
            expect_pf=0,
            word_before_reset=f"0x{w4:08x}",
            word=f"0x{w5:08x}",
        )
        close_graded_window(self.logger)
