# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""REFERENCE_COUNTER, the watchdog and wakeup timers, the timer bus shape and WDOG_REGWEN.

no_cpu on ``lsu_stub_all_live`` with ``+skip_fuse_sense`` and
``+sep_edn_jtag_reset_waive`` (the ``sep_reset_n`` override pulse of leg L
resets the crypto engines without isolation). Eight legs run in one leaf, in
this order, over the CPU-LSU master on ``s_axi``:

* Leg R. ``REFERENCE_COUNTER`` counts ``clk_ref_i`` edges at five clock ratios
  ``k`` of {2, 3, 5, 8, 13} in a drawn order; a 64-bit write reloads it with
  and without a carry into the high word; a cold reset restarts it
  (``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``, ``REFERENCE_COUNTER``;
  ``hw/sys/sep/doc/clk_rst.adoc``, Clock Distribution).
* Leg T. The bark status and then the bite request follow the count reads that
  reach the bark and bite thresholds, neither earlier than threshold - A nor
  later than threshold + A + D_pass in count (D_pass: the most the count
  advances over one poll pass), a larger bark threshold barks later in
  count, thresholds near 2^32 do not wrap, and ``INTR_TEST`` forces the bark
  status without a bite (``hw/sys/sep/doc/watchdog.adoc``, Bark Interrupt and
  Bite Reset; ``aon_timer.adoc``).
* Leg W. The wakeup expiry follows the 64-bit threshold across the 32-bit
  boundary at prescaler 0, 1 and a drawn value of 2 to 15, with both half
  orders, within the same early and late count bounds, and a larger threshold
  expires later in count.
* Leg S. Eleven watchdog registers, each at its own offset and so on the lane
  that its offset selects (both lanes together), answer 32-bit accesses of four
  patterns with the value their access type gives; ``WDOG_COUNT`` reads never
  fall while counting.
* Leg L. ``WDOG_REGWEN`` stays 0 after a write of 1, and ``regwen`` and the four
  thresholds keep their values over ``wdt_rst_ni``, ``dbg_rstb_i`` (VCS, full-CPU build only), a
  software engine reset and a ``sep_reset_n`` override; only the cold reset
  restores the defaults (``hw/sys/sep/doc/clk_rst.adoc``, Reset Architecture).
  With ``WDOG_REGWEN`` = 0, a ``WDOG_CTRL`` write does not change it, and writes
  to ``WDOG_COUNT`` and the wakeup registers land.
* Leg P. A pet restarts the watchdog count and holds off the bark; bark
  threshold 0 barks once enabled; a bark and then a bite threshold written at or
  below the running count fire.
* Leg K. The wakeup timer at prescaler 4095 with threshold 0: periods per
  count, the expired status and ``WKUP_CAUSE`` at the first prescaler
  completion, and a ``WKUP_CTRL`` write that restarts the prescaler.
* Leg C. A hi/lo read of the wakeup count across a low-word carry, and the
  hi/lo/hi read.

``aon_timer.adoc`` is
``vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/gen/adoc/aon_timer.adoc``.
Expected values come from the register description (generated register
metadata), the written values and the timer text below, never from a DUT read.
The timer core runs on ``clk_wdt_i``: "``clk_wdt_i`` | Watchdog timer clock. The
watchdog register interface uses ``clk_i``, with clock-domain crossings to the
timer core." (``hw/sys/sep/doc/clk_rst.adoc:25-26``) and "a dedicated watchdog
clock input (``clk_wdt_i``) ... for the always-on timer domain"
(``hw/sys/sep/doc/watchdog.adoc:23``). The OpenTitan ``aon_timer`` README
gives the count unit: "Once the timer is enabled, it increments on every tick
of the AON clock." (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:52``, the
watchdog); "Once the timer is enabled, it increments on every tick of the AON
clock, divided by a pre-scaler. The number of cycles per tick is one more than
the 12-bit WKUP_CTRL.prescaler field."
(``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:31-32``, the wakeup timer);
"there is a "bark" on every AON clock tick when the count is at least
WDOG_BARK_THOLD" (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:55``). So:

* CHK-WDT-RATE. In each watchdog run (``pause_in_sleep`` = 0), over the passes
  after the count leaves its start value, ``|dcount - E_wdt| <= A``, where
  ``dcount`` is the difference of the first and last count reads and ``E_wdt``
  the ``clk_wdt_i`` edges between them. ``A`` bounds the variation of the
  count-copy lag, so the bound holds for every healthy DUT by construction.
* CHK-WDT-BARK-TIME. In the runs that start from a count of 0, the
  ``clk_wdt_i`` periods from the count start to the status read that first shows
  the bark are at least ``WDOG_BARK_THOLD - A``, and the periods to the status
  read of the pass before it are below ``WDOG_BARK_THOLD + A``. The count start
  is measured from the DUT: for each count read, its ``clk_wdt_i`` edge index
  minus the count read. Control: at least one status read before the bark
  (``bark_pass`` >= 1), else CTRL-MISSING, because the late bound needs that
  read.
* CHK-WKUP-TIME. In each wakeup run, ``|dcount x (p + 1) - E_wdt| <= p + A``
  (``p``: the prescaler; ``p`` covers the tick phase at the two reads).

Each of these windows also requires ``dcount x (p + 1) > 2 x bound``, so a count
at half or twice the stated rate is outside the bound. Control: CTL-WDT-ENABLE
(with ``WDOG_CTRL.enable`` = 0 the count does not move; "When set to 1, the
watchdog timer will count.",
``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/data/aon_timer.hjson:261``).
Environment choices (logged): the edge allowance ``a`` of leg R, the count
allowance ``A`` of legs T, W and C, the clock period ``P_w`` of ``clk_wdt_i``, poll
bounds and wait lengths.

Legs L, P, K and C grade these sentences
(``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/`` is ``<aon>``). A read of
the timer returns a copy of the count from the clock-domain crossing ("Register
reads via the TL-UL interface (SYS domain) are synchronized to the slow clock (AON
domain)", ``<aon>/doc/theory_of_operation.md:25``). The copy is taken at or before
the read and may lag the live count by up to the allowance ``A``: no sentence gives
its age. A read follows the landing of every earlier write: "If software needs to guarantee
completion of a register write then it can read back the register value. This
will guarantee the completion of all previous writes to the peripheral."
(``<aon>/doc/theory_of_operation.md:27-28``). ``E(t0, t1)`` is the ``clk_wdt_i``
edges in (t0, t1].

* CHK-REGWEN-LOCK-SCOPE. ``WDOG_CTRL``, ``WDOG_BARK_THOLD`` and
  ``WDOG_BITE_THOLD`` carry ``regwen: "WDOG_REGWEN"``
  (``<aon>/data/aon_timer.hjson:257``, ``:274``, ``:287``); "Once cleared, the
  watchdog configuration will be locked until the next reset." (``:247``).
  ``WDOG_COUNT`` and ``WKUP_*`` carry no ``regwen`` (``:168-239``,
  ``:295-308``). With regwen 0 a ``WDOG_CTRL`` write reads back unchanged, and
  writes to ``WDOG_COUNT``, ``WKUP_CTRL``, ``WKUP_COUNT_HI/LO`` and
  ``WKUP_THOLD_HI/LO`` read back the written value. CTL-REGWEN-LOCKED grades the
  thresholds.
* CHK-WDT-PET. "Pet the watchdog by writing zero to the WDOG_COUNT register."
  (``<aon>/doc/programmers_guide.md:13``). The first count read after the pet is
  below the count read before it and at most ``E(pet write, read done)``.
* CHK-WDT-PET-HOLD. "To prevent the count reaching the bark or bite thresholds,
  software is expected to periodically reset the count" (``<aon>/README.md:57``).
  A pet at a count below ``WDOG_BARK_THOLD - 31`` gives a bark status of 0 on
  every status read up to one issued ``WDOG_BARK_THOLD + A + 1`` periods after
  the enable read-back, where an unpetted run barks (CHK-WDT-BARK-TIME).
  Controls: every count read of the hold window is below
  ``WDOG_BARK_THOLD - A``, so the petted count stays clear of the threshold
  (CTRL-MISSING otherwise); CTL-WDT-PET-BARK: the same run barks later, at a
  count of at least ``WDOG_BARK_THOLD - A``.
* CHK-WDT-THOLD-ZERO. "If the timer is enabled, there is a "bark" on every AON
  clock tick when the count is at least WDOG_BARK_THOLD." (``<aon>/README.md:55``).
  With ``WDOG_BARK_THOLD`` = 0 the bark status is 1 at the status read issued
  ``1 + A`` periods after the enable read-back. Control CTL-WDT-THOLD-ZERO: the
  status is 0 with the timer disabled.
* CHK-WDT-THOLD-BELOW. ``:55`` and "If the timer is enabled, there is also a
  "bite" on every AON clock tick when the count is at least WDOG_BITE_THOLD."
  (``<aon>/README.md:56``). A bark threshold, then a bite threshold, written at
  or below a count read taken before the write give the bark status 1, then
  ``wdt_timer_rst_req_o`` = 1, ``1 + A`` periods after the threshold read-back.
  Control CTL-WDT-THOLD-BELOW: each is 0 before its write.
* CHK-WKUP-PRESC-MAX. "The number of cycles per tick is one more than the
  12-bit WKUP_CTRL.prescaler field." (``<aon>/README.md:32``). At prescaler 4095
  the ``clk_wdt_i`` edges ``E`` over N = 32 consecutive count steps satisfy
  ``|E - N x 4096| < N/2``: a step is located to within the edges ``u`` of two
  back-to-back ``WKUP_COUNT_LO`` reads (edge indices taken at the pin before and
  after each read, plus one edge for an index taken in the time step of an
  edge), so ``E`` lies in a measured bracket of width ``u1 + u2 + 2``, and
  N x 4096 must lie in it. The width must be below N (CTRL-MISSING otherwise),
  so the measurement error is below N/2 and N x 4095 and N x 4097 fall outside.
  The steps after the enable and the restart writes against the write landing
  are logged only (the landing bracket is wider than one period of difference).
* CHK-WKUP-THOLD-ZERO. "Each time the pre-scaler completes when the count is at
  or above the threshold, two outputs become high" (``<aon>/README.md:35``); "The
  wakeup signal (`wkup_req_o`) stays high until software explicitly acknowledges
  it by software writing 0 to WKUP_CAUSE" (``<aon>/README.md:41``) and
  WKUP_CAUSE.cause is "AON timer requested wakeup, write 0 to clear."
  (``<aon>/data/aon_timer.hjson:350-351``). With
  threshold 0, the ``wkup_timer_expired`` status and ``WKUP_CAUSE`` read 0 at
  reads done at most 4096 periods after the enable write, and 1 at reads issued
  ``A`` periods after the count reads 1. Control CTL-WKUP-THOLD-ZERO: those early
  reads exist.
* CHK-WKUP-RESTART. "Each write to the register resets the internal prescaler
  count." (``<aon>/data/aon_timer.hjson:171``). A ``WKUP_CTRL`` write of the same value,
  ``restart_gap`` periods after the first count step, moves the next step: a
  read of the old count is issued at least 4096 periods after the first step.
* CHK-WKUP-CARRY-READ. ``<aon>/doc/programmers_guide.md:24-29`` (a read of
  ``WKUP_COUNT_HI`` gives 0x1, the count then increments past the low-word
  carry, a read of ``WKUP_COUNT_LO`` gives the low word, and "The final 64-bit
  value of `0x1_0000_0000` is incorrect.") and the hi/lo/hi pseudo code
  (``:33-45``). At prescaler 0 with the count preloaded 256 below the carry: the
  HI read is 0x1, the LO read is the low word in its count bounds, the second HI
  read is 0x2, and the hi/lo/hi value is in its count bounds, above the hi/lo
  value. Count bounds: ``[preload + E(enable read-back, issue) - 1 - A, preload +
  E(enable write, completion)]``, one count per period (``<aon>/README.md:31-32``,
  prescaler 0). ``A`` covers the age of the count copy, which no sentence states.
  Control CTL-WKUP-CARRY: the HI read completes fewer than 256
  periods after the enable write and the LO read is issued more than 256 + A
  periods after the read-back, so the carry falls between them even in a copy
  that lags by A.

``A`` appears in legs P and K only where a status crosses into ``clk_i``: the
same crossing that CHK-WDT-BARK-TIME bounds by ``A`` periods on every run, so a
healthy DUT cannot exceed it here. The count bounds of CHK-WDT-PET,
CHK-WKUP-PRESC-MAX and CHK-WKUP-RESTART use no allowance: a lagging copy only
lowers a CHK-WDT-PET read, and the two bracketed steps of CHK-WKUP-PRESC-MAX see the
same copy delay. The lower count bounds of CHK-WKUP-CARRY-READ use ``A`` for the
age of the count copy.
"A pet after the bark stops the bite" is not graded: no sentence states it.

Checkers: CHK-REFCNT-RATE, CHK-REFCNT-PHASE, CHK-REFCNT-WRITE,
CHK-REFCNT-RESET, CHK-WDT-ORDER, CHK-WDT-THOLD-MONO, CHK-WDT-MAX,
CHK-WDT-INTRTEST, CHK-WDT-ALERT-ACCESS, CHK-WKUP-WIDE, CHK-WKUP-LATER,
CHK-WDT-SHAPE, CHK-WDT-COHERENT, CHK-REGWEN-STICKY, CHK-REGWEN-HOLD,
CHK-REGWEN-COLD, CHK-WDT-RATE, CHK-WDT-BARK-TIME, CHK-WKUP-TIME,
CHK-REGWEN-LOCK-SCOPE, CHK-WDT-PET, CHK-WDT-PET-HOLD, CHK-WDT-THOLD-ZERO,
CHK-WDT-THOLD-BELOW, CHK-WKUP-PRESC-MAX, CHK-WKUP-THOLD-ZERO, CHK-WKUP-RESTART,
CHK-WKUP-CARRY-READ. Controls (not counted): CTL-WDT-ENABLE, CTL-WDT-THOLD,
CTL-WDT-PAUSE, CTL-WKUP-SMALL, CTL-WKUP-CAUSE, CTL-REGWEN-LOCKED,
CTL-WDT-PET-BARK, CTL-WDT-THOLD-ZERO, CTL-WDT-THOLD-BELOW, CTL-WKUP-THOLD-ZERO,
CTL-WKUP-CARRY.

The graded window (owner code of this test) opens at leg R and closes for the
enable control run, the small wakeup control runs and the recovery resets of a
held bite request, and at the end of the leaf.
"""

from __future__ import annotations

import bisect

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiOp
from env.sep_edge_timer import SepEdgeTimer, SepPinEdgeCounter
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, WDT_TIMER
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, capture_resp_handshake, take_handshake
from seq_lib.sep_sw_reset_seq import SepSwReset
from seq_lib.sep_wdt_aon_seq import (
    INTR_STATE,
    INTR_TEST,
    WDOG_BARK_THOLD,
    WDOG_BITE_THOLD,
    WDOG_COUNT,
    WDOG_CTRL,
    WDOG_REGWEN,
    WKUP_CAUSE,
    WKUP_COUNT_HI,
    WKUP_COUNT_LO,
    WKUP_CTRL,
    WKUP_THOLD_HI,
    WKUP_THOLD_LO,
    SepWdtAon,
)

TEST = "sep_timer_clock_contract_test"
M32 = 0xFFFF_FFFF
M64 = (1 << 64) - 1

REFCNT = SEP_CPU_CTRL.addr("REFERENCE_COUNTER")
REFCNT_FIELD = SEP_CPU_CTRL.field_mask("REFERENCE_COUNTER", "rc")
ALERT_TEST = WDT_TIMER.addr("ALERT_TEST")
BARK_BIT = WDT_TIMER.field_mask("INTR_STATE", "wdog_timer_bark")
WKUP_BIT = WDT_TIMER.field_mask("INTR_STATE", "wkup_timer_expired")
INTR_FIELDS = WDT_TIMER.mask("INTR_STATE")
WDOG_CTRL_FIELDS = WDT_TIMER.mask("WDOG_CTRL")
WDOG_EN = WDT_TIMER.field_mask("WDOG_CTRL", "enable")
WDOG_PAUSE = WDT_TIMER.field_mask("WDOG_CTRL", "pause_in_sleep")
WKUP_CTRL_FIELDS = WDT_TIMER.mask("WKUP_CTRL")
WKUP_EN = WDT_TIMER.field_mask("WKUP_CTRL", "enable")
WKUP_PRESC_LSB = WDT_TIMER.field_lsb("WKUP_CTRL", "prescaler")
REGWEN_FIELD = WDT_TIMER.field_mask("WDOG_REGWEN", "regwen")
CAUSE_FIELD = WDT_TIMER.field_mask("WKUP_CAUSE", "cause")

# Register name -> (address, field mask, RDL reset value).
AON = {
    name: (WDT_TIMER.addr(name), WDT_TIMER.mask(name), WDT_TIMER.reset(name))
    for name in (
        "WKUP_CTRL",
        "WKUP_THOLD_HI",
        "WKUP_THOLD_LO",
        "WKUP_COUNT_HI",
        "WKUP_COUNT_LO",
        "WDOG_REGWEN",
        "WDOG_CTRL",
        "WDOG_BARK_THOLD",
        "WDOG_BITE_THOLD",
        "WDOG_COUNT",
        "INTR_STATE",
        "WKUP_CAUSE",
    )
}
WALK_REGS = (
    "WKUP_CTRL",
    "WKUP_THOLD_HI",
    "WKUP_THOLD_LO",
    "WKUP_COUNT_HI",
    "WKUP_COUNT_LO",
    "WDOG_BARK_THOLD",
    "WDOG_BITE_THOLD",
)
THOLD_REGS = ("WDOG_BARK_THOLD", "WDOG_BITE_THOLD", "WKUP_THOLD_HI", "WKUP_THOLD_LO")

# Environment choices (logged; the specification gives no tolerance).
RATIOS = (2, 3, 5, 8, 13)
P_W = 8  # clk_wdt_i period in clk_i periods
EDGE_ALLOW = 2  # a: clk_ref_i edges
COUNT_ALLOW = 4  # A: clk_wdt_i counts
RATE_WAIT_REF = 400  # clk_ref_i periods between the two rate reads
POLL_GAP = 2  # clk_i cycles between poll reads of a register write
POLL_READS = 200  # bound on the poll reads of one register write
REFCNT_ARM_REF = 200  # clk_ref_i cycles bound of the 2^40 arm poll
REFCNT_POLL = 400  # bound on the reads of the reload poll
WDT_WAIT = 64  # clk_wdt_i periods of the wait in the controls and leg L
RESET_BOUND = 4_000  # clk_i cycles for a reset tap to read 1
OVRD_CYCLES = 24  # clk_i cycles the sep_reset_n override holds the reset
PULSE_CYCLES = 16  # clk_i cycles of a wdt_rst_ni or dbg_rstb_i pulse
PHASE_GRID_PS = 125  # grid of the drawn clock start phases (one tenth of a clk_i period)
REF_SETTLE = 64  # clk_ref_i cycles between the bring-up and the first rate read
TWO40 = 1 << 40
FAR = 1 << 33  # least distance of a reload value from the count before its write
WDOG_FAR_BARK = 0xFFFF_0000  # bark threshold far above every count of leg P
WDOG_FAR_BITE = 0xFFFF_FFF0  # bite threshold far above every count of leg P
PRESC_MAX = 0xFFF  # largest 12-bit WKUP_CTRL.prescaler
PRESC_EARLY = 64  # clk_wdt_i periods before an expected count step that a poll starts
PRESC_LATE = 512  # clk_wdt_i periods after an expected count step that a poll gives up
CARRY_MARGIN = 256  # counts from the leg K carry preload to the 32-bit carry
PRESC_RUN = 32  # N: count steps between the two bracketed steps of CHK-WKUP-PRESC-MAX


def _gap(order: list[int]) -> str:
    return ",".join(str(g) for g in order)


class _Cfg:
    """Seed-drawn configuration of the leaf (single source of truth)."""

    def __init__(self, seed: int, sys_ps: int, *, dbg_cell: bool) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.ratios = list(RATIOS)
        rng.shuffle(self.ratios)
        # Start phases on a PHASE_GRID_PS grid, so every delay is exact at the
        # simulator precision.
        self.ref_phase_ps = [
            PHASE_GRID_PS * rng.randrange(0, k * sys_ps // PHASE_GRID_PS) for k in self.ratios
        ]
        self.wdt_phase_ps = PHASE_GRID_PS * rng.randrange(0, P_W * sys_ps // PHASE_GRID_PS)
        self.walk_gaps = [0, 1, 2, 3, 4]
        rng.shuffle(self.walk_gaps)
        # Reload values. Each value is at least FAR away from the count before its
        # write (the count after bring-up, the other reload value, and 2^40, the
        # arm value of the cold-reset step), so a read taken before the write
        # lands can never fall inside the window [W, W + edges + a].
        lim = (1 << 64) - (1 << 32)

        def far(w: int, others: tuple[int, ...]) -> bool:
            return w >= FAR and all(abs(w - o) > FAR for o in others)

        while True:
            w = rng.randrange(0, lim)
            if (w & M32) < 0xFFFF_FFF0 and far(w, (TWO40,)):
                self.w_lo = w
                break
        while True:
            w = (rng.randrange(0, lim >> 32) << 32) | rng.randrange(0xFFFF_FFF0, 1 << 32)
            if far(w, (TWO40, self.w_lo)):
                self.w_hi = w
                break
        self.reload_order = ["W_lo", "W_hi"]
        rng.shuffle(self.reload_order)
        self.b = rng.randrange(32, 65)
        self.d = rng.randrange(self.b + 32, self.b + 65)
        self.b2 = rng.randrange(self.b + 32, self.b + 65)
        self.bm = rng.randrange(0xFFFF_FF00, 0xFFFF_FF11)
        self.dm = rng.randrange(self.bm + 32, self.bm + 49)
        self.p_m = rng.randrange(2, 16)
        self.presc = [0, 1, self.p_m]
        rng.shuffle(self.presc)
        self.p_m_order = rng.choice(("hi_first", "lo_first"))
        self.ts = rng.randrange(40, 201)
        self.g = rng.randrange(16, 33)
        self.r = rng.randrange(32, 49)
        self.walk_order = list(WALK_REGS)
        rng.shuffle(self.walk_order)
        self.walk_one = {name: 1 << rng.randrange(32) for name in WALK_REGS}
        self.walk_one["INTR"] = 1 << rng.randrange(2)
        self.walk_one["WDOG_CTRL"] = 1 << rng.randrange(2)
        self.walk_one["WKUP_CAUSE"] = 1 << rng.randrange(32)
        self.read_gaps = [rng.randrange(0, 41) for _ in range(64)]
        self.coh_bark = rng.randrange(0xFFFF_0000, 0xFFFF_8000)
        self.coh_bite = rng.randrange(self.coh_bark + 1, 1 << 32)
        self.xb, self.xd, self.xh, self.xl = (rng.randrange(1, 1 << 32) for _ in range(4))
        self.locked_b = self.xb ^ rng.randrange(1, 1 << 32)
        self.locked_d = self.xd ^ rng.randrange(1, 1 << 32)
        events = ["WDT_PULSE", "SW_RESET", "OVRD"] + (["DBG_PULSE"] if dbg_cell else [])
        rng.shuffle(events)
        self.events = events
        self.repeat = rng.randrange(1, 4)
        self.cold_bark = rng.randrange(1, 1 << 32)
        # Leg L lock scope: the bit flips of the locked WDOG_CTRL write and the
        # flips of the writable registers (each nonzero, so every write changes
        # the register).
        self.scope_ctrl_flip = rng.choice((WDOG_EN, WDOG_PAUSE, WDOG_EN | WDOG_PAUSE))
        self.scope_count_flip = rng.randrange(1, 1 << 32)
        self.scope_presc_flip = rng.randrange(1, 1 << 12) << WKUP_PRESC_LSB
        self.scope_wk_flip = [rng.randrange(1, 1 << 32) for _ in range(4)]
        # Leg P: pet run bark threshold and pet count; the count at which a
        # threshold at or below the count is written, and its offsets.
        self.pb = rng.randrange(96, 161)
        self.pet_at = rng.randrange(self.pb // 2, self.pb - 31)
        self.below_c = rng.randrange(32, 65)
        self.below_off = rng.randrange(0, 17)
        self.bite_off = rng.randrange(0, 17)
        # Leg K: clk_wdt_i periods from the first count step to the restart write.
        self.restart_gap = rng.randrange(512, 1025)

    def order_of(self, p: int) -> str:
        if p == 0:
            return "hi_first"
        if p == 1:
            return "lo_first"
        return self.p_m_order

    def patterns(self, name: str) -> list[int]:
        return [0, M32, self.walk_one[name], 0xA5A5_A5A5]


@pyuvm.test()
class sep_timer_clock_contract_test(sep_base_test):
    """REFERENCE_COUNTER, watchdog, wakeup timer, timer bus shape and WDOG_REGWEN."""

    required_evidence = (
        "CHK-REFCNT-RATE",
        "CHK-REFCNT-PHASE",
        "CHK-REFCNT-WRITE",
        "CHK-REFCNT-RESET",
        "CHK-WDT-ORDER",
        "CHK-WDT-THOLD-MONO",
        "CHK-WDT-MAX",
        "CHK-WDT-INTRTEST",
        "CHK-WDT-ALERT-ACCESS",
        "CHK-WKUP-WIDE",
        "CHK-WKUP-LATER",
        "CHK-WDT-SHAPE",
        "CHK-WDT-COHERENT",
        "CHK-REGWEN-STICKY",
        "CHK-REGWEN-HOLD",
        "CHK-REGWEN-COLD",
        "CHK-WDT-RATE",
        "CHK-WDT-BARK-TIME",
        "CHK-WKUP-TIME",
        "CHK-REGWEN-LOCK-SCOPE",
        "CHK-WDT-PET",
        "CHK-WDT-PET-HOLD",
        "CHK-WDT-THOLD-ZERO",
        "CHK-WDT-THOLD-BELOW",
        "CHK-WKUP-PRESC-MAX",
        "CHK-WKUP-THOLD-ZERO",
        "CHK-WKUP-RESTART",
        "CHK-WKUP-CARRY-READ",
    )

    # -- primitives -----------------------------------------------------------

    def _now(self) -> int:
        return int(get_sim_time("ps"))

    def _edges(self, pin: str, t0: int, t1: int) -> int:
        """Rising edges of ``pin`` at the pin with a time in (t0, t1]."""
        e = self.pins.edge_times(pin)
        return bisect.bisect_right(e, t1) - bisect.bisect_right(e, t0)

    async def _refcnt_read(self) -> tuple[int, int]:
        """One 64-bit REFERENCE_COUNTER read. Returns (value, read-data sample time)."""
        task = cocotb.start_soon(capture_resp_handshake("r"))
        seq = SepAxiAccessSeq("refcnt_rd", op=SepAxiOp.READ, addr=REFCNT, length=8, size=3)
        await self.start_seq(seq)
        t = take_handshake(task)
        if not seq.resp_ok or t is None:
            raise AssertionError(f"REFERENCE_COUNTER read resp={seq.resp_code} t={t}")
        return seq.rdata & REFCNT_FIELD, t

    async def _refcnt_write(self, value: int) -> int:
        """One 64-bit REFERENCE_COUNTER write. Returns the B handshake time."""
        task = cocotb.start_soon(capture_resp_handshake("b"))
        seq = SepAxiAccessSeq(
            "refcnt_wr", op=SepAxiOp.WRITE, addr=REFCNT, wdata=value, length=8, size=3
        )
        await self.start_seq(seq)
        t = take_handshake(task)
        if not seq.resp_ok or t is None:
            raise AssertionError(f"REFERENCE_COUNTER write resp={seq.resp_code} t={t}")
        return t

    async def _rd(self, addr: int) -> int:
        return await self.wdt.read(addr)

    async def _wr(self, addr: int, value: int) -> None:
        await self.wdt.write(addr, value & M32)

    async def _poll_eq(self, name: str, addr: int, want: int, mask: int, chk: str) -> int:
        """Poll a timer register until its field bits equal ``want``. Returns the read."""
        got = 0
        for n in range(1, POLL_READS + 1):
            got = await self._rd(addr)
            if (got & mask) == (want & mask):
                if got & ~mask & M32:
                    self.logger.info("OBS-WDT-RSVD: reg=%s raw=0x%08x", name, got)
                return got
            await ClockCycles(cocotb.top.clk_i, POLL_GAP)
        raise AssertionError(
            f"{chk} FAIL: {name} never read 0x{want & mask:x} on mask 0x{mask:x} in "
            f"{POLL_READS} reads (last 0x{got:08x})"
        )

    async def _wait_wdt(self, periods: int) -> None:
        await ClockCycles(cocotb.top.clk_wdt_i, periods)

    async def _wait_high(self, sig, name: str) -> int:
        for n in range(1, RESET_BOUND + 1):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd(sig, allow_unknown=True):
                await RisingEdge(cocotb.top.clk_i)
                return n
        raise AssertionError(f"{name} did not read 1 within {RESET_BOUND} clk_i cycles")

    async def _sample_at_ar(self, sig) -> int:
        """``sig`` at the next s_axi AR handshake (read-only phase)."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if dut.s_axi_arvalid.value == 1 and dut.s_axi_arready.value == 1:
                return self.rd(sig)

    def _gate(self, on: bool) -> None:
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    # -- leg R ------------------------------------------------------------------

    async def _reload_poll(
        self, tw: int, w: int, chk: str, *, bound_ref: int | None = None
    ) -> tuple[int, int, int, int]:
        """Poll REFERENCE_COUNTER after a write of ``w`` (B handshake at ``tw``).

        The register description asks software to poll until the readback
        reflects the written value: at or above ``w`` and at most the
        ``clk_ref_i`` edges since the write (plus the allowance ``a``) above it.
        Reads before the load crosses return the old count, which the draw keeps
        far from ``w``; they are counted as stale. A DUT that ignores the write or
        loads another value never enters the window and fails the bounded poll.
        Returns (first readback in the window, polls, edges since the write, stale reads).
        """
        stale = 0
        v = 0
        for polls in range(1, REFCNT_POLL + 1):
            v, t = await self._refcnt_read()
            e = self._edges("clk_ref_i", tw, t)
            if bound_ref is not None and e > bound_ref:
                break
            if w <= v <= w + e + EDGE_ALLOW:
                return v, polls, e, stale
            stale += 1
        raise AssertionError(
            f"{chk} FAIL: W=0x{w:016x} no readback in [W, W + edges + {EDGE_ALLOW}] within "
            f"{REFCNT_POLL} reads{'' if bound_ref is None else f' or {bound_ref} clk_ref_i cycles'}"
            f" (last 0x{v:016x}, stale reads {stale})"
        )

    async def _leg_r(self) -> None:
        cfg = self.tcfg
        dut = cocotb.top
        sys_ps = self.sys_ps
        # The counter leaves reset through a reset synchronizer on clk_ref_i whose
        # latency the specification does not state; the rate passes start after it.
        await ClockCycles(dut.clk_ref_i, REF_SETTLE)
        for idx, k in enumerate(cfg.ratios):
            if idx:
                await FallingEdge(dut.clk_ref_i)
                self.restart_clock(
                    "clk_ref_i", k * self.cfg.sys_clk_period_ns, cfg.ref_phase_ps[idx]
                )
                await ClockCycles(dut.clk_ref_i, 8)
            self.logger.info(
                "LEG-R ratio=%d clk_ref_period_ps=%d start_phase_ps=%d",
                k,
                k * sys_ps,
                cfg.ref_phase_ps[idx],
            )
            r1, t1 = await self._refcnt_read()
            await ClockCycles(dut.clk_ref_i, RATE_WAIT_REF)
            r2, t2 = await self._refcnt_read()
            delta = r2 - r1
            e = self._edges("clk_ref_i", t1, t2)
            n = self._edges("clk_i", t1, t2)
            diff = abs(delta - e)
            line = f"k={k} delta={delta} E_ref={e} abs_diff={diff} clk_i_cycles={n} allowance={EDGE_ALLOW}"
            assert diff <= EDGE_ALLOW, f"CHK-REFCNT-RATE FAIL: {line}"
            assert abs(delta - n) * 4 > n, (
                f"CHK-REFCNT-RATE FAIL: delta within 25% of clk_i: {line}"
            )
            self.logger.info("CHK-REFCNT-RATE PASS: %s", line)
            if k == 5:
                prev, tp = r2, t2
                deltas, edges, diffs = [], [], []
                for g in cfg.walk_gaps:
                    if g:
                        await ClockCycles(dut.clk_i, g)
                    v, t = await self._refcnt_read()
                    d = v - prev
                    ee = self._edges("clk_ref_i", tp, t)
                    assert v >= prev, (
                        f"CHK-REFCNT-PHASE FAIL: read fell 0x{prev:x} -> 0x{v:x} gap={g}"
                    )
                    deltas.append(d)
                    edges.append(ee)
                    diffs.append(abs(d - ee))
                    prev, tp = v, t
                line = (
                    f"k=5 gaps={_gap(cfg.walk_gaps)} deltas={deltas} E_ref={edges} monotone=1 "
                    f"max_abs_diff={max(diffs)} allowance={EDGE_ALLOW}"
                )
                assert max(diffs) <= EDGE_ALLOW, f"CHK-REFCNT-PHASE FAIL: {line}"
                self.logger.info("CHK-REFCNT-PHASE PASS: %s", line)

        # Reload, twice, in the drawn order.
        for tag in cfg.reload_order:
            w = cfg.w_lo if tag == "W_lo" else cfg.w_hi
            tw = await self._refcnt_write(w)
            first, polls, e_w, stale = await self._reload_poll(tw, w, "CHK-REFCNT-WRITE")
            prev = first
            for _ in range(16):
                v, _t = await self._refcnt_read()
                assert v >= prev, f"CHK-REFCNT-WRITE FAIL: read fell 0x{prev:x} -> 0x{v:x}"
                prev = v
            while self._edges("clk_ref_i", tw, self._now()) < 32:
                await RisingEdge(dut.clk_ref_i)
            last, _t = await self._refcnt_read()
            assert last >= prev, f"CHK-REFCNT-WRITE FAIL: read fell 0x{prev:x} -> 0x{last:x}"
            carry = int((w & M32) >= 0xFFFF_FFF0)
            want_hi = (w >> 32) + carry
            assert (last >> 32) == want_hi, (
                f"CHK-REFCNT-WRITE FAIL: W=0x{w:016x} high word 0x{last >> 32:x} after 32 "
                f"edges, expected 0x{want_hi:x} (carry={carry})"
            )
            self.logger.info(
                "CHK-REFCNT-WRITE PASS: W=0x%016x first_readback=0x%016x polls=%d monotone=1 "
                "carry=%d E_w=%d stale_reads=%d last=0x%016x",
                w,
                first,
                polls,
                carry,
                e_w,
                stale,
                last,
            )

        # Cold reset with the counter armed at 2^40 or above.
        tw = await self._refcnt_write(TWO40)
        armed, polls, e_a, stale = await self._reload_poll(
            tw, TWO40, "CHK-REFCNT-RESET", bound_ref=REFCNT_ARM_REF
        )
        self.logger.info(
            "REFCNT-ARMED LOG: armed_readback=0x%016x polls=%d E_since_write=%d stale_reads=%d",
            armed,
            polls,
            e_a,
            stale,
        )
        rises = len(self.rst_timer.rises())
        await self.pulse_rst_ni(hold_cycles=PULSE_CYCLES, release_bound=RESET_BOUND)
        t_rel = self.rst_timer.rises()[rises]
        r_r, t_r = await self._refcnt_read()
        e_r = self._edges("clk_ref_i", t_rel, t_r)
        assert r_r < TWO40 and r_r <= e_r + EDGE_ALLOW, (
            f"CHK-REFCNT-RESET FAIL: armed_readback=0x{armed:x} first_read=0x{r_r:x} "
            f"E_since_release={e_r} allowance={EDGE_ALLOW}"
        )
        prev = r_r
        for _ in range(16):
            v, _t = await self._refcnt_read()
            assert v >= prev, f"CHK-REFCNT-RESET FAIL: read fell 0x{prev:x} -> 0x{v:x}"
            prev = v
        assert prev > r_r, f"CHK-REFCNT-RESET FAIL: no increase after the reset (0x{r_r:x})"
        self.logger.info(
            "CHK-REFCNT-RESET PASS: armed_readback=0x%016x first_read=0x%x E_since_release=%d "
            "last=0x%x",
            armed,
            r_r,
            e_r,
            prev,
        )

    # -- leg T ------------------------------------------------------------------

    async def _wdt_baseline(self, bx: int, dx: int, c0: int, *, graded: bool) -> None:
        dut = cocotb.top
        for attempt in (0, 1):
            await self._wr(WDOG_CTRL, 0)
            await self._wr(INTR_STATE, BARK_BIT)
            await self._wr(WDOG_COUNT, c0)
            await self._wr(WDOG_BARK_THOLD, bx)
            await self._wr(WDOG_BITE_THOLD, dx)
            ok = False
            cnt = st = req = 0
            for _ in range(POLL_READS):
                cnt = await self._rd(WDOG_COUNT)
                st = await self._rd(INTR_STATE)
                req = self.rd(dut.wdt_timer_rst_req_o)
                if cnt == c0 and not (st & BARK_BIT) and not req:
                    ok = True
                    break
                await ClockCycles(dut.clk_i, POLL_GAP)
            if ok:
                return
            if attempt == 0 and cnt == c0 and not (st & BARK_BIT) and req:
                # The bite request holds until the cold reset (watchdog.adoc, Bark
                # Interrupt and Bite Reset); recover with the graded window closed.
                self.logger.info("OBS-WDT-BITE-HOLD: wdt_timer_rst_req_o=1 at the baseline")
                self._gate(False)
                await self.pulse_rst_ni(hold_cycles=PULSE_CYCLES, release_bound=RESET_BOUND)
                if graded:
                    self._gate(True)
                continue
            break
        raise AssertionError(
            f"WDT baseline failed: WDOG_COUNT=0x{cnt:x} (want 0x{c0:x}) INTR_STATE=0x{st:x} "
            f"wdt_timer_rst_req_o={req}"
        )

    async def _wdt_run(self, bx: int, dx: int, c0: int, chk: str) -> dict:
        """One watchdog run (baseline, enable, poll loop). Returns the pass list."""
        dut = cocotb.top
        await self._wdt_baseline(bx, dx, c0, graded=True)
        await self._wr(WDOG_CTRL, WDOG_EN)
        t_en = self._now()
        passes = []
        limit = (dx - c0 + 128) * P_W * 4
        start = self.pins.count["clk_i"]
        while True:
            task = cocotb.start_soon(self._sample_at_ar(dut.wdt_timer_rst_req_o))
            st = await self._rd(INTR_STATE)
            t_st = self._now()
            bite = take_handshake(task)
            assert bite is not None, f"{chk} FAIL: no AR handshake seen for the INTR_STATE read"
            cnt = await self._rd(WDOG_COUNT)
            t_c = self._now()
            passes.append(
                {"bark": int(bool(st & BARK_BIT)), "bite": bite, "count": cnt, "t": t_st, "tc": t_c}
            )
            if passes[-1]["bark"] and bite and cnt >= dx:
                break
            if self.pins.count["clk_i"] - start > limit:
                raise AssertionError(
                    f"{chk} FAIL: bx=0x{bx:x} dx=0x{dx:x} c0=0x{c0:x}: no pass with bark set, "
                    f"bite high and count >= dx within {limit} clk_i cycles (last {passes[-1]})"
                )
        counts = [p["count"] for p in passes]
        d_pass = max([b - a for a, b in zip(counts, counts[1:])] or [0])
        return {"passes": passes, "t_en": t_en, "d_pass": d_pass}

    def _grade_order(self, run: dict, bx: int, dx: int, c0: int, chk: str, tag: str) -> dict:
        passes = run["passes"]
        a = COUNT_ALLOW
        late = a + run["d_pass"]
        prev = c0
        bark_pass = bite_pass = None
        for i, p in enumerate(passes):
            c = p["count"]
            assert c >= prev, f"{chk} FAIL: run={tag} count fell 0x{prev:x} -> 0x{c:x} pass={i}"
            prev = c
            if p["bark"] and c < bx - a:
                raise AssertionError(
                    f"{chk} FAIL: run={tag} bark set at pass {i} with count 0x{c:x} < bx - A "
                    f"(bx=0x{bx:x} A={a})"
                )
            if p["bite"] and not p["bark"]:
                raise AssertionError(f"{chk} FAIL: run={tag} bite high with bark clear at pass {i}")
            if p["bite"] and c < dx - a:
                raise AssertionError(
                    f"{chk} FAIL: run={tag} bite high at pass {i} with count 0x{c:x} < dx - A "
                    f"(dx=0x{dx:x} A={a})"
                )
            if bark_pass is None and p["bark"]:
                bark_pass = i
            if bite_pass is None and p["bite"]:
                bite_pass = i
        assert bark_pass is not None and bite_pass is not None
        # Late bound in count space: the count read of the last pass before the
        # status read that shows the event is below threshold + A + D_pass (A: the
        # count copy lag; D_pass: the most the count advances over one pass).
        for ev, at, thr in (("bark", bark_pass, bx), ("bite", bite_pass, dx)):
            before = passes[at - 1]["count"] if at else c0
            assert before < thr + late, (
                f"{chk} FAIL: run={tag} {ev} late: first seen at pass {at}, the count read of "
                f"the pass before was 0x{before:x} >= threshold 0x{thr:x} + A {a} + D_pass "
                f"{run['d_pass']}"
            )
        assert bark_pass < bite_pass, (
            f"{chk} FAIL: run={tag} bark first seen at pass {bark_pass}, not before the bite "
            f"at pass {bite_pass} (bx=0x{bx:x} dx=0x{dx:x})"
        )
        return {
            "count_at_bark": passes[bark_pass]["count"],
            "count_at_bite": passes[bite_pass]["count"],
            "bark_pass": bark_pass,
            "bite_pass": bite_pass,
            "late": late,
            "t_bark": passes[bark_pass]["t"],
        }

    def _precondition(self, run: dict, min_gap: int, tag: str) -> None:
        d = run["d_pass"]
        self.logger.info(
            "D-PASS LOG: run=%s D_pass=%d min_gap=%d allowance=%d", tag, d, min_gap, COUNT_ALLOW
        )
        assert 2 * d < min_gap - COUNT_ALLOW, (
            f"precondition FAIL: run={tag} 2 x D_pass ({2 * d}) is not below the smallest "
            f"threshold gap of the leg minus A ({min_gap} - {COUNT_ALLOW})"
        )

    def _grade_rate(self, run: dict, c_start: int, p: int, chk: str, tag: str) -> str:
        """Count rate against ``clk_wdt_i`` edges, one count per (p + 1) periods.

        Only the passes whose count read is above ``c_start`` are used, so the
        enable crossing before the count leaves its start value is not in the
        window. Returns the graded fields.
        """
        seed = self.tcfg.seed
        per = p + 1
        bound = p + COUNT_ALLOW
        started = [x for x in run["passes"] if x["count"] > c_start]
        if len(started) < 2:
            raise AssertionError(
                f"{chk} FAIL: seed={seed} run={tag} {len(started)} count reads above the "
                f"start value 0x{c_start:x}, need 2"
            )
        first, last = started[0], started[-1]
        dcount = last["count"] - first["count"]
        e = self._edges("clk_wdt_i", first["tc"], last["tc"])
        diff = abs(dcount * per - e)
        line = (
            f"seed={seed} run={tag} p={p} dcount={dcount} E_wdt={e} abs_diff={diff} "
            f"bound={bound} reads={len(started)}"
        )
        if dcount * per <= 2 * bound:
            raise AssertionError(
                f"{chk} FAIL: window too short (dcount x (p+1) <= 2 x bound): {line}"
            )
        if diff > bound:
            raise AssertionError(f"{chk} FAIL: {line}")
        return line

    def _grade_bark_time(self, run: dict, r: dict, bx: int, tag: str) -> str:
        """Bark time from a count of 0, in ``clk_wdt_i`` periods. Returns the fields."""
        seed = self.tcfg.seed
        t0 = run["t_en"]
        passes = run["passes"]
        starts = [
            self._edges("clk_wdt_i", t0, x["tc"]) - x["count"] for x in passes if x["count"] > 0
        ]
        if not starts:
            raise AssertionError(
                f"CHK-WDT-BARK-TIME FAIL: seed={seed} run={tag} no count read above 0"
            )
        k = r["bark_pass"]
        if k < 1:
            raise AssertionError(
                f"CTRL-MISSING CHK-WDT-BARK-TIME: seed={seed} run={tag} bark_pass={k}: "
                "no status read before the bark, so the late bound has no pass to grade"
            )
        seen = self._edges("clk_wdt_i", t0, passes[k]["t"]) - max(starts)
        before = self._edges("clk_wdt_i", t0, passes[k - 1]["t"]) - min(starts)
        line = (
            f"seed={seed} run={tag} bark_thold={bx} periods_at_bark_seen={seen} "
            f"periods_at_pass_before={before} start_spread={max(starts) - min(starts)} "
            f"allowance={COUNT_ALLOW} bark_pass={k}"
        )
        if seen < bx - COUNT_ALLOW:
            raise AssertionError(f"CHK-WDT-BARK-TIME FAIL: bark early: {line}")
        if before >= bx + COUNT_ALLOW:
            raise AssertionError(f"CHK-WDT-BARK-TIME FAIL: bark late: {line}")
        return line

    async def _leg_t(self) -> None:
        cfg = self.tcfg
        dut = cocotb.top
        b, d, b2, bm, dm = cfg.b, cfg.d, cfg.b2, cfg.bm, cfg.dm
        d2 = b2 + (d - b)
        min_gap = min(b, d - b, b2 - b, 32, dm - bm)

        # Base run.
        base = await self._wdt_run(b, d, 0, "CHK-WDT-ORDER")
        self._precondition(base, min_gap, "base")
        rb = self._grade_order(base, b, d, 0, "CHK-WDT-ORDER", "base")
        self.logger.info(
            "CHK-WDT-ORDER PASS: run=base bark=%d bite=%d allowance=%d count_at_bark=%d "
            "bark_early=0 bite_with_bark_clear=0 bite_early=0 count_at_bite=%d passes=%d "
            "bark_pass=%d bite_pass=%d late_bound=%d",
            b,
            d,
            COUNT_ALLOW,
            rb["count_at_bark"],
            rb["count_at_bite"],
            len(base["passes"]),
            rb["bark_pass"],
            rb["bite_pass"],
            rb["late"],
        )
        self.logger.info(
            "CHK-WDT-RATE PASS: %s", self._grade_rate(base, 0, 0, "CHK-WDT-RATE", "base")
        )

        # Larger bark threshold.
        larger = await self._wdt_run(b2, d2, 0, "CHK-WDT-ORDER")
        self._precondition(larger, min_gap, "larger")
        rl = self._grade_order(larger, b2, d2, 0, "CHK-WDT-ORDER", "larger")
        self.logger.info(
            "CHK-WDT-ORDER PASS: run=larger bark=%d bite=%d allowance=%d count_at_bark=%d "
            "bark_early=0 bite_with_bark_clear=0 bite_early=0 count_at_bite=%d passes=%d "
            "bark_pass=%d bite_pass=%d late_bound=%d",
            b2,
            d2,
            COUNT_ALLOW,
            rl["count_at_bark"],
            rl["count_at_bite"],
            len(larger["passes"]),
            rl["bark_pass"],
            rl["bite_pass"],
            rl["late"],
        )
        c1, c2 = rb["count_at_bark"], rl["count_at_bark"]
        line = (
            f"b={b} count_at_bark={c1} b2={b2} count_at_bark2={c2} allowance={COUNT_ALLOW} "
            f"later={int(c2 > c1)}"
        )
        assert c2 >= b2 - COUNT_ALLOW and c2 > c1, f"CHK-WDT-THOLD-MONO FAIL: {line}"
        self.logger.info("CHK-WDT-THOLD-MONO PASS: %s", line)
        self.logger.info(
            "CHK-WDT-RATE PASS: %s", self._grade_rate(larger, 0, 0, "CHK-WDT-RATE", "larger")
        )
        for run, r, bx, tag in ((base, rb, b, "base"), (larger, rl, b2, "larger")):
            self.logger.info("CHK-WDT-BARK-TIME PASS: %s", self._grade_bark_time(run, r, bx, tag))

        # Thresholds near 2^32.
        mx = await self._wdt_run(bm, dm, bm - 32, "CHK-WDT-MAX")
        self._precondition(mx, min_gap, "max")
        rm = self._grade_order(mx, bm, dm, bm - 32, "CHK-WDT-MAX", "max")
        self.logger.info(
            "CHK-WDT-RATE PASS: %s", self._grade_rate(mx, bm - 32, 0, "CHK-WDT-RATE", "max")
        )
        assert min(p["count"] for p in mx["passes"]) >= bm - 32
        self.logger.info(
            "CHK-WDT-MAX PASS: b=0x%x d=0x%x count_at_bark=0x%x count_at_bite=0x%x early=0",
            bm,
            dm,
            rm["count_at_bark"],
            rm["count_at_bite"],
        )

        # Enable control (window closed).
        bx, dx = 0xFFFF_0000, 0xFFFF_0010
        self._gate(False)
        await self._wdt_baseline(bx, dx, 0, graded=False)
        await self._wr(WDOG_CTRL, WDOG_EN)
        for _ in range(POLL_READS):
            c = await self._rd(WDOG_COUNT)
            if c >= 2:
                break
        assert c >= 2, f"CTL-WDT-ENABLE FAIL: count never reached 2 (0x{c:x})"
        await self._wr(WDOG_CTRL, 0)
        await self._wait_wdt(WDT_WAIT)
        r1 = await self._rd(WDOG_COUNT)
        await self._wait_wdt(WDT_WAIT)
        r2 = await self._rd(WDOG_COUNT)
        st = await self._rd(INTR_STATE)
        await self._wr(WDOG_CTRL, WDOG_EN)
        await self._wait_wdt(WDT_WAIT)
        r3 = await self._rd(WDOG_COUNT)
        line = (
            f"disabled_at_count={c} reads=0x{r1:x},0x{r2:x} equal bark={int(bool(st & BARK_BIT))} "
            f"reenabled_advance={int(r3 > r2)}"
        )
        assert r1 == r2 and not (st & BARK_BIT) and r3 > r2, f"CTL-WDT-ENABLE FAIL: {line}"
        self.logger.info("CTL-WDT-ENABLE: %s", line)
        await self._wr(WDOG_CTRL, 0)
        self._gate(True)

        # Forced bark with enable 0 and 1.
        await self._wdt_baseline(bx, dx, 0, graded=True)
        samples = {"high": 0, "n": 0, "last": 0}
        stop = {"v": False}

        async def _watch() -> None:
            while not stop["v"]:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                samples["n"] += 1
                samples["last"] = self._now()
                samples["high"] += self.rd(dut.wdt_timer_rst_req_o)

        watch = cocotb.start_soon(_watch())
        for en in (0, 1):
            if en:
                await self._wr(WDOG_CTRL, WDOG_EN)
            await self._wr(INTR_TEST, BARK_BIT)
            await self._poll_eq("INTR_STATE", INTR_STATE, BARK_BIT, BARK_BIT, "CHK-WDT-INTRTEST")
            await self._wr(INTR_STATE, BARK_BIT)
            await self._poll_eq("INTR_STATE", INTR_STATE, 0, BARK_BIT, "CHK-WDT-INTRTEST")
            cnt = await self._rd(WDOG_COUNT)
            assert cnt < bx, f"CHK-WDT-INTRTEST FAIL: count 0x{cnt:x} not far below bx"
            if watch.done():
                watch.result()
                raise AssertionError(
                    f"CHK-WDT-INTRTEST FAIL: wdt_timer_rst_req_o watcher ended early "
                    f"(enable={en} samples={samples['n']})"
                )
            assert samples["high"] == 0, (
                f"CHK-WDT-INTRTEST FAIL: wdt_timer_rst_req_o high on {samples['high']} of "
                f"{samples['n']} clk_i edges (enable={en})"
            )
            self.logger.info(
                "CHK-WDT-INTRTEST PASS: enable=%d status=1 cleared=1 bite=0 count=0x%x "
                "rst_req_samples=%d",
                en,
                cnt,
                samples["n"],
            )
        # The watcher ends only on the stop flag, so a normal join shows that it sampled
        # every clk_i edge from the first force to the end of the second clear.
        t_end = self._now()
        stop["v"] = True
        await watch
        assert samples["last"] >= t_end and samples["high"] == 0, (
            f"CHK-WDT-INTRTEST FAIL: wdt_timer_rst_req_o high on {samples['high']} of "
            f"{samples['n']} clk_i edges, last sample {samples['last']} ps, window end {t_end} ps"
        )
        await self._wr(WDOG_CTRL, 0)

        # pause_in_sleep and ALERT_TEST.
        await self._wr(WDOG_CTRL, WDOG_PAUSE)
        v1 = await self._poll_eq(
            "WDOG_CTRL", WDOG_CTRL, WDOG_PAUSE, WDOG_CTRL_FIELDS, "CTL-WDT-PAUSE"
        )
        await self._wr(WDOG_CTRL, 0)
        v0 = await self._poll_eq("WDOG_CTRL", WDOG_CTRL, 0, WDOG_CTRL_FIELDS, "CTL-WDT-PAUSE")
        self.logger.info("CTL-WDT-PAUSE: write1_read=0x%x write0_read=0x%x", v1, v0)
        seq = SepAxiAccessSeq(
            "alert_test",
            op=SepAxiOp.WRITE,
            addr=ALERT_TEST,
            wdata=1,
            length=4,
            size=2,
            allow_unverified_write_resp=True,
        )
        await self.start_seq(seq)
        assert not seq.timed_out, "CHK-WDT-ALERT-ACCESS FAIL: no response"
        self.logger.info("CHK-WDT-ALERT-ACCESS PASS: response=%d", seq.resp_code)

    # -- leg W ------------------------------------------------------------------

    async def _wkup_count(self) -> tuple[int, int]:
        """One coherent 64-bit wakeup count read. Returns (value, time of the low-word read)."""
        for _ in range(4):
            hi = await self._rd(WKUP_COUNT_HI)
            lo = await self._rd(WKUP_COUNT_LO)
            t_lo = self._now()
            hi2 = await self._rd(WKUP_COUNT_HI)
            if hi == hi2:
                return (hi << 32) | lo, t_lo
        raise AssertionError("wakeup count high word changed on four read sets")

    async def _wkup_run(self, p: int, order: str, thr: int, pre: int, tag: str) -> dict:
        ctrl = p << WKUP_PRESC_LSB
        await self._wr(WKUP_CTRL, ctrl)
        regs = {
            "WKUP_THOLD_HI": (WKUP_THOLD_HI, thr >> 32),
            "WKUP_THOLD_LO": (WKUP_THOLD_LO, thr & M32),
            "WKUP_COUNT_HI": (WKUP_COUNT_HI, pre >> 32),
            "WKUP_COUNT_LO": (WKUP_COUNT_LO, pre & M32),
        }
        names = (
            ("WKUP_THOLD_HI", "WKUP_THOLD_LO", "WKUP_COUNT_HI", "WKUP_COUNT_LO")
            if order == "hi_first"
            else ("WKUP_THOLD_LO", "WKUP_THOLD_HI", "WKUP_COUNT_LO", "WKUP_COUNT_HI")
        )
        for name in names:
            addr, val = regs[name]
            await self._wr(addr, val)
            await self._poll_eq(name, addr, val, AON[name][1], "CHK-WKUP-WIDE")
        await self._wr(INTR_STATE, WKUP_BIT)
        st0 = await self._poll_eq("INTR_STATE", INTR_STATE, 0, WKUP_BIT, "CHK-WKUP-WIDE")
        await self._wr(WKUP_CTRL, ctrl | WKUP_EN)
        t_en = self._now()
        passes = []
        gap = thr - pre
        limit = (gap + 64) * (p + 1) * P_W * 8
        start = self.pins.count["clk_i"]
        prev = pre
        while True:
            st = await self._rd(INTR_STATE)
            t_st = self._now()
            cnt, t_c = await self._wkup_count()
            passes.append({"st": int(bool(st & WKUP_BIT)), "count": cnt, "t": t_st, "tc": t_c})
            assert cnt >= prev, f"{tag}: wakeup count fell 0x{prev:x} -> 0x{cnt:x}"
            prev = cnt
            if passes[-1]["st"]:
                break
            if self.pins.count["clk_i"] - start > limit:
                raise AssertionError(
                    f"CHK-WKUP-WIDE FAIL: run={tag} p={p} thr=0x{thr:x}: the expired status "
                    f"did not set within {limit} clk_i cycles (last count 0x{cnt:x})"
                )
        counts = [x["count"] for x in passes]
        d_pass = max([b - a for a, b in zip(counts, counts[1:])] or [0])
        return {
            "passes": passes,
            "t_en": t_en,
            "status_before": st0 & WKUP_BIT,
            "d_pass": d_pass,
            "n": passes[-1]["count"],
            "t": passes[-1]["t"],
        }

    def _grade_wide(self, run: dict, thr: int, pre: int, tag: str) -> int:
        """Early and late bounds of the expiry in count space. Returns the late bound."""
        passes = run["passes"]
        for i, x in enumerate(passes):
            if x["st"] and x["count"] < thr - COUNT_ALLOW:
                raise AssertionError(
                    f"CHK-WKUP-WIDE FAIL: run={tag} status set at pass {i} with count "
                    f"0x{x['count']:x} < thr - A (thr=0x{thr:x} A={COUNT_ALLOW})"
                )
        # The run stops at the first pass that reads the status set. The count read
        # of the pass before it is below thr + A + D_pass (A: the count copy lag;
        # D_pass: the most the count advances over one pass).
        late = COUNT_ALLOW + run["d_pass"]
        before = passes[-2]["count"] if len(passes) > 1 else pre
        assert before < thr + late, (
            f"CHK-WKUP-WIDE FAIL: run={tag} expiry late: the count read of the pass before the "
            f"status set was 0x{before:x} >= thr 0x{thr:x} + A {COUNT_ALLOW} + D_pass "
            f"{run['d_pass']}"
        )
        return late

    async def _wkup_stop(self) -> None:
        await self._wr(WKUP_CTRL, 0)
        await self._poll_eq("WKUP_CTRL", WKUP_CTRL, 0, WKUP_CTRL_FIELDS, "CHK-WKUP-WIDE")
        await self._wr(INTR_STATE, WKUP_BIT)
        await self._poll_eq("INTR_STATE", INTR_STATE, 0, WKUP_BIT, "CHK-WKUP-WIDE")

    async def _leg_w(self) -> None:
        cfg = self.tcfg
        r = cfg.r
        pre = 0xFFFF_FFF0
        thr1, thr2 = (1 << 32) | r, (1 << 32) | (2 * r)
        min_gap = min(thr1 - pre, thr2 - thr1)
        for p in cfg.presc:
            order = cfg.order_of(p)
            self.logger.info("LEG-W p=%d half_order=%s", p, order)
            # Control run (window closed).
            self._gate(False)
            ctl = await self._wkup_run(p, order, cfg.ts, cfg.ts - cfg.g, "control")
            line = (
                f"p={p} thr=0x0_{cfg.ts:x} preload=0x0_{cfg.ts - cfg.g:x} "
                f"status_before={ctl['status_before']} status_after=1"
            )
            assert ctl["status_before"] == 0, f"CTL-WKUP-SMALL FAIL: {line}"
            self.logger.info("CTL-WKUP-SMALL: %s", line)
            await self._wkup_stop()
            self._gate(True)
            runs = []
            for k, thr in ((1, thr1), (2, thr2)):
                run = await self._wkup_run(p, order, thr, pre, f"run{k}")
                self._precondition(run, min_gap, f"wkup p={p} run{k}")
                late = self._grade_wide(run, thr, pre, f"p={p} run{k}")
                self.logger.info(
                    "CHK-WKUP-TIME PASS: %s",
                    self._grade_rate(run, pre, p, "CHK-WKUP-TIME", f"wkup_run{k}"),
                )
                assert run["status_before"] == 0
                self.logger.info(
                    "CHK-WKUP-WIDE PASS: p=%d run=%d class=CROSS32 thr=0x%x_%08x preload=0x%x_%08x "
                    "allowance=%d status_before=0 count_at_expiry=0x%x passes=%d half_order=%s "
                    "late_bound=%d",
                    p,
                    k,
                    thr >> 32,
                    thr & M32,
                    pre >> 32,
                    pre & M32,
                    COUNT_ALLOW,
                    run["n"],
                    len(run["passes"]),
                    order,
                    late,
                )
                runs.append(run)
                await self._wkup_stop()
            n1, n2 = runs[0]["n"], runs[1]["n"]
            line = f"p={p} r={r} n1=0x{n1:x} n2=0x{n2:x} allowance={COUNT_ALLOW} status_between=0"
            assert n2 >= thr2 - COUNT_ALLOW and n2 > n1, f"CHK-WKUP-LATER FAIL: {line}"
            self.logger.info("CHK-WKUP-LATER PASS: %s", line)

    # -- leg S ------------------------------------------------------------------

    async def _leg_s(self) -> None:
        cfg = self.tcfg
        cause = await self._rd(WKUP_CAUSE)
        assert cause & CAUSE_FIELD, (
            f"CTL-WKUP-CAUSE FAIL: WKUP_CAUSE=0x{cause:x} after the wakeup expiries"
        )
        t_clear = self._now()
        await self._wr(WKUP_CAUSE, 0)
        after = await self._poll_eq("WKUP_CAUSE", WKUP_CAUSE, 0, CAUSE_FIELD, "CTL-WKUP-CAUSE")
        # The clear crosses the same clock boundary as a set would, so its measured landing
        # time bounds the wait before a WKUP_CAUSE write is graded.
        landing_ps = self._now() - t_clear
        self.logger.info(
            "CTL-WKUP-CAUSE: before_clear=%d after_clear=%d landing_ps=%d",
            cause & 1,
            after & CAUSE_FIELD,
            landing_ps,
        )

        n_checks = 0
        lanes = set()
        differs = {name: False for name in WALK_REGS}
        for pi in range(4):
            for name in cfg.walk_order:
                addr, mask, reset = AON[name]
                pat = cfg.patterns(name)[pi]
                wv = pat & ~WKUP_EN if name == "WKUP_CTRL" else pat
                await self._wr(addr, wv)
                got = await self._poll_eq(name, addr, wv, mask, "CHK-WDT-SHAPE")
                lane = "hi" if addr & 0x4 else "lo"
                fc = field_compare(got, wv, mask)
                lanes.add(lane)
                n_checks += 1
                differs[name] |= (got & mask) != (reset & mask)
                self.logger.info("WDT-SHAPE LOG: reg=%s lane=%s %s", name, lane, fc.fields())
            # WKUP_CAUSE (RW0C): a write cannot set it. A write lands no later than twice
            # the measured landing time of the clear plus 16 clk_wdt_i periods, so the
            # cause is read back-to-back from the write response to the end of that
            # window, and every read is graded.
            pat = cfg.patterns("WKUP_CAUSE")[pi]
            await self._wr(WKUP_CAUSE, pat)
            t_wr = self._now()
            reads = []
            while True:
                got = await self._rd(WKUP_CAUSE)
                reads.append(got)
                now = self._now()
                if now - t_wr >= 2 * landing_ps and self._edges("clk_wdt_i", t_wr, now) >= 16:
                    break
            bad = [r for r in reads if not field_compare(r, 0, CAUSE_FIELD).ok]
            fc = field_compare(bad[0] if bad else reads[-1], 0, CAUSE_FIELD)
            assert not bad, (
                f"CHK-WDT-SHAPE FAIL: WKUP_CAUSE set by a write of 0x{pat:x}: {fc.fields()} "
                f"set_reads={len(bad)}/{len(reads)} window=2x{landing_ps}ps+16 clk_wdt_i"
            )
            self.logger.info(
                "WDT-SHAPE LOG: reg=WKUP_CAUSE pattern=0x%08x %s reads=%d "
                "window=2x%dps+16 clk_wdt_i",
                pat,
                fc.fields(),
                len(reads),
                landing_ps,
            )
            n_checks += 1
        assert all(differs.values()), f"CHK-WDT-SHAPE FAIL: dead register {differs}"

        # Interrupt registers.
        for pi in range(4):
            pat = cfg.patterns("INTR")[pi]
            await self._wr(INTR_STATE, M32)
            await self._poll_eq("INTR_STATE", INTR_STATE, 0, INTR_FIELDS, "CHK-WDT-SHAPE")
            await self._wr(INTR_TEST, pat)
            await self._poll_eq(
                "INTR_STATE", INTR_STATE, pat & INTR_FIELDS, INTR_FIELDS, "CHK-WDT-SHAPE"
            )
            await self._wr(INTR_TEST, M32)
            await self._poll_eq("INTR_STATE", INTR_STATE, INTR_FIELDS, INTR_FIELDS, "CHK-WDT-SHAPE")
            await self._wr(INTR_STATE, pat)
            await self._poll_eq(
                "INTR_STATE", INTR_STATE, INTR_FIELDS & ~pat, INTR_FIELDS, "CHK-WDT-SHAPE"
            )
            await self._wr(INTR_STATE, M32)
            n_checks += 3
            self.logger.info("WDT-SHAPE LOG: reg=INTR_STATE/INTR_TEST pattern=0x%08x exact", pat)

        # WDOG_CTRL walk with the thresholds far above the count.
        await self._wr(WDOG_BARK_THOLD, 0xFFFF_FFF0)
        await self._wr(WDOG_BITE_THOLD, 0xFFFF_FFF8)
        await self._wr(WDOG_COUNT, 0)
        lanes.add("hi")
        for pi in range(4):
            pat = cfg.patterns("WDOG_CTRL")[pi]
            await self._wr(WDOG_CTRL, pat)
            got = await self._poll_eq(
                "WDOG_CTRL", WDOG_CTRL, pat, WDOG_CTRL_FIELDS, "CHK-WDT-SHAPE"
            )
            self.logger.info("WDT-SHAPE LOG: reg=WDOG_CTRL pattern=0x%08x readback=0x%x", pat, got)
            n_checks += 1
        await self._wr(WDOG_CTRL, 0)
        await self._poll_eq("WDOG_CTRL", WDOG_CTRL, 0, WDOG_CTRL_FIELDS, "CHK-WDT-SHAPE")
        assert lanes == {"lo", "hi"}, f"CHK-WDT-SHAPE FAIL: lanes {lanes}"
        self.logger.info(
            "CHK-WDT-SHAPE PASS: regs=%d lanes=2 patterns=4 exact types=RW|RW1C|W|RW0C checks=%d",
            len(WALK_REGS) + 4,
            n_checks,
        )

        # Coherent count reads.
        await self._wr(WDOG_COUNT, 0)
        await self._poll_eq("WDOG_COUNT", WDOG_COUNT, 0, AON["WDOG_COUNT"][1], "CHK-WDT-COHERENT")
        await self._wr(WDOG_CTRL, WDOG_EN)
        gaps = iter(cfg.read_gaps)
        segs: list[list[int]] = [[], []]
        ctrl_reads: list[int] = []
        for i in range(1, 33):
            await ClockCycles(cocotb.top.clk_i, next(gaps) + 1)
            segs[0].append(await self._rd(WDOG_COUNT))
            if i in (8, 24):
                ctrl_reads.append(await self._rd(WDOG_CTRL))
            if i == 16:
                await self._wr(WDOG_BARK_THOLD, cfg.coh_bark)
                await self._wr(WDOG_BITE_THOLD, cfg.coh_bite)
                for name, val in (
                    ("WDOG_BARK_THOLD", cfg.coh_bark),
                    ("WDOG_BITE_THOLD", cfg.coh_bite),
                ):
                    got = await self._poll_eq(
                        name, AON[name][0], val, AON[name][1], "CHK-WDT-COHERENT"
                    )
                    self.logger.info(
                        "CTL-WDT-THOLD: reg=%s lane=%s pattern=0x%08x readback=0x%08x "
                        "timer=enabled",
                        name,
                        "hi" if AON[name][0] & 4 else "lo",
                        val,
                        got,
                    )
        await self._wr(WDOG_CTRL, 0)
        await self._wr(WDOG_COUNT, 0x1000)
        await self._poll_eq(
            "WDOG_COUNT", WDOG_COUNT, 0x1000, AON["WDOG_COUNT"][1], "CHK-WDT-COHERENT"
        )
        await self._wr(WDOG_CTRL, WDOG_EN)
        for _ in range(32):
            await ClockCycles(cocotb.top.clk_i, next(gaps) + 1)
            segs[1].append(await self._rd(WDOG_COUNT))
        await self._wr(WDOG_CTRL, 0)
        inc = 0
        for si, seg in enumerate(segs):
            for a, b in zip(seg, seg[1:]):
                assert b >= a, f"CHK-WDT-COHERENT FAIL: segment {si} count fell 0x{a:x} -> 0x{b:x}"
                inc += int(b > a)
        for c in ctrl_reads:
            fc = field_compare(c, WDOG_EN, WDOG_CTRL_FIELDS)
            assert fc.ok, f"CHK-WDT-COHERENT FAIL: WDOG_CTRL while counting {fc.fields()}"
            if c & ~WDOG_CTRL_FIELDS & M32:
                self.logger.info("OBS-WDT-RSVD: reg=WDOG_CTRL raw=0x%08x", c)
        assert segs[1][0] >= 0x1000, f"CHK-WDT-COHERENT FAIL: first read 0x{segs[1][0]:x} < 0x1000"
        assert inc >= 3, f"CHK-WDT-COHERENT FAIL: only {inc} increases"
        self.logger.info(
            "CHK-WDT-COHERENT PASS: reads=%d segments=2 monotone=1 increases=%d ctrl_reads=%d ctrl=1",
            len(segs[0]) + len(segs[1]),
            inc,
            len(ctrl_reads),
        )

    # -- leg L ------------------------------------------------------------------

    async def _read_lock_state(self) -> dict[str, int]:
        out = {"WDOG_REGWEN": await self._rd(WDOG_REGWEN)}
        for name in THOLD_REGS:
            out[name] = await self._rd(AON[name][0])
        return out

    def _grade_hold(self, st: dict[str, int], ev: str, when: str) -> None:
        cfg = self.tcfg
        want = {
            "WDOG_REGWEN": 0,
            "WDOG_BARK_THOLD": cfg.xb,
            "WDOG_BITE_THOLD": cfg.xd,
            "WKUP_THOLD_HI": cfg.xh,
            "WKUP_THOLD_LO": cfg.xl,
        }
        for name, w in want.items():
            fc = field_compare(st[name], w, AON[name][1])
            assert fc.ok, f"CHK-REGWEN-HOLD FAIL: event={ev} {when} reg={name} {fc.fields()}"

    async def _event(self, ev: str) -> None:
        dut = cocotb.top
        if ev == "WDT_PULSE":
            await RisingEdge(dut.clk_i)
            dut.wdt_rst_ni_i.value = 0
            await ClockCycles(dut.clk_i, PULSE_CYCLES)
            await ReadOnly()
            low = self.rd(dut.sep_cpu_reset_n_o)
            await RisingEdge(dut.clk_i)
            dut.wdt_rst_ni_i.value = 1
            assert low == 0, "sep_cpu_reset_n_o did not fall during the wdt_rst_ni pulse"
            await self._wait_high(dut.sep_cpu_reset_n_o, "sep_cpu_reset_n_o")
        elif ev == "DBG_PULSE":
            # Runs only on the full-CPU build, where dbg_rstb_i resets the EL2 debug
            # module; the debug reset input of the core wrapper (tap dbg_rst_l_probe_o,
            # tied to 1 on the CPU stub build) must read 0 in the pulse.
            load = dut.dbg_rst_l_probe_o
            await RisingEdge(dut.clk_i)
            dut.dbg_rstb_i.value = 0
            await ClockCycles(dut.clk_i, PULSE_CYCLES)
            await ReadOnly()
            low = self.rd(load)
            await RisingEdge(dut.clk_i)
            dut.dbg_rstb_i.value = 1
            assert low == 0, "dbg_rst_l_probe_o did not fall during the dbg_rstb_i pulse"
            await ClockCycles(dut.clk_i, PULSE_CYCLES)
            self.n_dbg += 1
        elif ev == "SW_RESET":
            hmac = dut.hmac_gated_rst_n_probe_o
            self.swrst.value = await self.swrst.read_back()
            await self.swrst.park("hmac")
            for n in range(RESET_BOUND):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                if not self.rd(hmac):
                    break
            assert not self.rd(hmac), "ip_rst_n[3] did not fall after the SW_RESET_N write of 0"
            await RisingEdge(dut.clk_i)
            await self.swrst.release("hmac")
            await self._wait_high(hmac, "ip_rst_n[3]")
        elif ev == "OVRD":
            await RisingEdge(dut.clk_i)
            dut.jtag_sep_reset_n_val_i.value = 0
            dut.jtag_sep_reset_n_ovrd_i.value = 1
            await ClockCycles(dut.clk_i, OVRD_CYCLES)
            await ReadOnly()
            low = self.rd(dut.dbg_sep_reset_n_o)
            await RisingEdge(dut.clk_i)
            dut.jtag_sep_reset_n_ovrd_i.value = 0
            assert low == 0, "dbg_sep_reset_n_o did not fall under the sep_reset_n override"
            await self._wait_high(dut.dbg_sep_reset_n_o, "dbg_sep_reset_n_o")
        else:
            raise ValueError(ev)

    async def _lock_scope(self) -> None:
        """CHK-REGWEN-LOCK-SCOPE, with ``WDOG_REGWEN`` = 0 and both thresholds locked.

        A write to ``WDOG_CTRL`` does not change it; writes to ``WDOG_COUNT`` and
        the five wakeup registers land. Each write flips bits of the value read
        before it, so a landed write and an ignored write read differently. The
        landed wakeup writes come after the locked ``WDOG_CTRL`` write and are read
        back before ``WDOG_CTRL`` is read, so that read follows the completion of
        the locked write. ``WKUP_THOLD_HI`` and ``WKUP_THOLD_LO`` get their leg L
        values back at the end.
        """
        cfg = self.tcfg
        seed = cfg.seed
        chk = "CHK-REGWEN-LOCK-SCOPE"
        ctrl0 = await self._rd(WDOG_CTRL)
        ctrl_try = (ctrl0 ^ cfg.scope_ctrl_flip) & WDOG_CTRL_FIELDS
        await self.wdt.write_tolerant(WDOG_CTRL, ctrl_try)
        landed = []
        wk = (
            ("WKUP_CTRL", WKUP_CTRL, cfg.scope_presc_flip, WKUP_CTRL_FIELDS),
            ("WKUP_COUNT_HI", WKUP_COUNT_HI, cfg.scope_wk_flip[0], AON["WKUP_COUNT_HI"][1]),
            ("WKUP_COUNT_LO", WKUP_COUNT_LO, cfg.scope_wk_flip[1], AON["WKUP_COUNT_LO"][1]),
            ("WKUP_THOLD_HI", WKUP_THOLD_HI, cfg.scope_wk_flip[2], AON["WKUP_THOLD_HI"][1]),
            ("WKUP_THOLD_LO", WKUP_THOLD_LO, cfg.scope_wk_flip[3], AON["WKUP_THOLD_LO"][1]),
        )
        for name, addr, flip, mask in wk:
            old = await self._rd(addr)
            new = (old ^ flip) & mask
            await self._wr(addr, new)
            await self._poll_eq(name, addr, new, mask, chk)
            landed.append(f"{name}=0x{old & mask:x}->0x{new:x}")
        ctrl1 = await self._rd(WDOG_CTRL)
        fc = field_compare(ctrl1, ctrl0, WDOG_CTRL_FIELDS)
        assert fc.ok, (
            f"{chk} FAIL: seed={seed} WDOG_CTRL changed by a write of 0x{ctrl_try:x} with "
            f"WDOG_REGWEN = 0: {fc.fields()}"
        )
        old = await self._rd(WDOG_COUNT)
        new = old ^ cfg.scope_count_flip
        await self._wr(WDOG_COUNT, new)
        await self._poll_eq("WDOG_COUNT", WDOG_COUNT, new, AON["WDOG_COUNT"][1], chk)
        landed.append(f"WDOG_COUNT=0x{old:x}->0x{new:x}")
        for name, val in (("WKUP_THOLD_HI", cfg.xh), ("WKUP_THOLD_LO", cfg.xl)):
            await self._wr(AON[name][0], val)
            await self._poll_eq(name, AON[name][0], val, AON[name][1], chk)
        self.logger.info(
            "%s PASS: seed=%d regwen=0 WDOG_CTRL=0x%x write=0x%x unchanged=1 landed=%s",
            chk,
            seed,
            ctrl1 & WDOG_CTRL_FIELDS,
            ctrl_try,
            ",".join(landed),
        )

    async def _leg_l(self) -> None:
        cfg = self.tcfg
        r0 = await self._rd(WDOG_REGWEN)
        assert r0 & REGWEN_FIELD, f"CHK-REGWEN-STICKY FAIL: regwen reads 0x{r0:x} before the clear"
        for name, val in zip(THOLD_REGS, (cfg.xb, cfg.xd, cfg.xh, cfg.xl)):
            await self._wr(AON[name][0], val)
            await self._poll_eq(name, AON[name][0], val, AON[name][1], "CHK-REGWEN-HOLD")
        await self._wr(WDOG_REGWEN, 0)
        await self._poll_eq("WDOG_REGWEN", WDOG_REGWEN, 0, REGWEN_FIELD, "CHK-REGWEN-STICKY")
        await self._wr(WDOG_REGWEN, 1)
        await self._wait_wdt(WDT_WAIT)
        r1 = await self._rd(WDOG_REGWEN)
        fc = field_compare(r1, 0, REGWEN_FIELD)
        assert fc.ok, f"CHK-REGWEN-STICKY FAIL: write of 1 after the clear {fc.fields()}"
        self.logger.info("CHK-REGWEN-STICKY PASS: before=1 write1_after_clear regwen=0")
        await self.wdt.write_tolerant(WDOG_BARK_THOLD, cfg.locked_b)
        await self.wdt.write_tolerant(WDOG_BITE_THOLD, cfg.locked_d)
        await self._wait_wdt(WDT_WAIT)
        lb = await self._rd(WDOG_BARK_THOLD)
        ld = await self._rd(WDOG_BITE_THOLD)
        assert lb == cfg.xb and ld == cfg.xd, (
            f"CTL-REGWEN-LOCKED FAIL: bark=0x{lb:x} bite=0x{ld:x} after locked writes"
        )
        self.logger.info("CTL-REGWEN-LOCKED: bark=0x%08x bite=0x%08x", lb, ld)
        await self._lock_scope()

        done = []
        last = None
        for rep in range(cfg.repeat):
            for ev in cfg.events:
                await self._event(ev)
                st = await self._read_lock_state()
                self._grade_hold(st, ev, "first")
                await self._wait_wdt(WDT_WAIT)
                st = await self._read_lock_state()
                self._grade_hold(st, ev, "after_wait")
                last = st
                done.append(ev)
                self.logger.info("REGWEN-HOLD LOG: rep=%d event=%s %s", rep, ev, st)
        if self.dbg_cell:
            # On the VCS full-CPU build the dbg_rstb_i cell must have run and been graded.
            assert self.n_dbg == cfg.repeat and self.n_dbg == done.count("DBG_PULSE"), (
                f"CHK-REGWEN-HOLD FAIL: event=DBG_PULSE ran {self.n_dbg} times, expected "
                f"{cfg.repeat}; the dbg_rstb_i cell was not graded"
            )
            self.logger.info(
                "CHK-REGWEN-HOLD PASS: event=DBG_PULSE count=%d dbg_rst_l_low=1 regwen=0 "
                "bark=0x%08x bite=0x%08x wkup_hi=0x%08x wkup_lo=0x%08x unchanged",
                self.n_dbg,
                cfg.xb,
                cfg.xd,
                cfg.xh,
                cfg.xl,
            )
        self.logger.info(
            "CHK-REGWEN-HOLD PASS: events=%s regwen=0 bark=0x%08x bite=0x%08x wkup_hi=0x%08x "
            "wkup_lo=0x%08x unchanged",
            ",".join(done),
            cfg.xb,
            cfg.xd,
            cfg.xh,
            cfg.xl,
        )

        # Cold reset.
        armed = sum(
            1
            for name, w in (
                ("WDOG_REGWEN", 0),
                ("WDOG_BARK_THOLD", cfg.xb),
                ("WDOG_BITE_THOLD", cfg.xd),
                ("WKUP_THOLD_HI", cfg.xh),
                ("WKUP_THOLD_LO", cfg.xl),
            )
            if (last[name] & AON[name][1]) == (w & AON[name][1])
            and (w & AON[name][1]) != (AON[name][2] & AON[name][1])
        )
        # Control: the registers held their armed values before the reset.
        assert armed == 5, f"CHK-REGWEN-COLD FAIL: armed_before={armed}/5"
        await self.pulse_rst_ni(hold_cycles=PULSE_CYCLES, release_bound=RESET_BOUND)
        st = await self._read_lock_state()
        for name in ("WDOG_REGWEN",) + THOLD_REGS:
            fc = field_compare(st[name], AON[name][2], AON[name][1])
            assert fc.ok, f"CHK-REGWEN-COLD FAIL: reg={name} after the cold reset {fc.fields()}"
        await self._wr(WDOG_BARK_THOLD, cfg.cold_bark)
        await self._poll_eq(
            "WDOG_BARK_THOLD",
            WDOG_BARK_THOLD,
            cfg.cold_bark,
            AON["WDOG_BARK_THOLD"][1],
            "CHK-REGWEN-COLD",
        )
        self.logger.info(
            "CHK-REGWEN-COLD PASS: regwen=%d bark=%d bite=%d wkup_hi=%d wkup_lo=%d write_lands=1 "
            "armed_before=%d/5",
            st["WDOG_REGWEN"] & REGWEN_FIELD,
            st["WDOG_BARK_THOLD"],
            st["WDOG_BITE_THOLD"],
            st["WKUP_THOLD_HI"],
            st["WKUP_THOLD_LO"],
            armed,
        )

    # -- leg P ------------------------------------------------------------------

    async def _timed_rd(self, addr: int) -> tuple[int, int, int]:
        """One register read. Returns (value, issue time, completion time)."""
        s = self._now()
        v = await self._rd(addr)
        return v, s, self._now()

    async def _pet(self) -> None:
        """CHK-WDT-PET and CHK-WDT-PET-HOLD, control CTL-WDT-PET-BARK."""
        cfg = self.tcfg
        seed = cfg.seed
        pb, pet_at = cfg.pb, cfg.pet_at
        a = COUNT_ALLOW
        await self._wdt_baseline(pb, WDOG_FAR_BITE, 0, graded=True)
        await self._wr(WDOG_CTRL, WDOG_EN)
        await self._poll_eq("WDOG_CTRL", WDOG_CTRL, WDOG_EN, WDOG_CTRL_FIELDS, "CHK-WDT-PET")
        # The read-back follows the landing of the enable, so the count starts
        # no later than t_en_rb (theory_of_operation.md:27-28).
        t_en_rb = self._now()
        start = self.pins.count["clk_wdt_i"]
        limit = 4 * pb + 512

        def _late(what: str) -> None:
            if self.pins.count["clk_wdt_i"] - start > limit:
                raise AssertionError(
                    f"CHK-WDT-PET FAIL: seed={seed} {what} within {limit} clk_wdt_i periods"
                )

        # Before the pet: the count climbs to pet_at, below pb - 31.
        cnt = 0
        while cnt < pet_at:
            st = await self._rd(INTR_STATE)
            cnt = await self._rd(WDOG_COUNT)
            assert not (st & BARK_BIT), (
                f"CHK-WDT-PET-HOLD FAIL: seed={seed} bark set before the pet with count "
                f"0x{cnt:x} < bark threshold {pb}"
            )
            _late(f"count never reached pet_at={pet_at} (last 0x{cnt:x})")
        c_before = cnt
        t_pet = self._now()
        await self._wr(WDOG_COUNT, 0)
        c_after, _s, d_after = await self._timed_rd(WDOG_COUNT)
        e_pet = self._edges("clk_wdt_i", t_pet, d_after)
        line = (
            f"seed={seed} count_before=0x{c_before:x} count_after=0x{c_after:x} "
            f"E_since_pet_write={e_pet}"
        )
        if not (c_after < c_before and c_after <= e_pet):
            raise AssertionError(f"CHK-WDT-PET FAIL: count does not restart from 0: {line}")
        self.logger.info("CHK-WDT-PET PASS: %s", line)

        # The hold window ends with a status read issued pb + A + 1 clk_wdt_i
        # periods after the enable read-back: from the count start, CHK-WDT-BARK-TIME
        # shows a bark by bx + A periods, so an unpetted run barks before that read.
        hold_end = pb + a + 1
        reads = 0
        max_cnt = c_after
        while True:
            st, s_st, _d = await self._timed_rd(INTR_STATE)
            cnt = await self._rd(WDOG_COUNT)
            reads += 1
            max_cnt = max(max_cnt, cnt)
            if st & BARK_BIT:
                raise AssertionError(
                    f"CHK-WDT-PET-HOLD FAIL: seed={seed} bark set after the pet with count "
                    f"0x{cnt:x}, status read {reads} (bark threshold {pb})"
                )
            if self._edges("clk_wdt_i", t_en_rb, s_st) >= hold_end:
                break
            _late("the hold window did not close")
        if max_cnt >= pb - a:
            raise AssertionError(
                f"CTRL-MISSING CHK-WDT-PET-HOLD: seed={seed} count 0x{max_cnt:x} reached "
                f"pb - A in the hold window (pb={pb}, A={a})"
            )
        self.logger.info(
            "CHK-WDT-PET-HOLD PASS: seed=%d bark_thold=%d pet_at_count=%d status_reads=%d "
            "bark=0 hold_end_periods=%d max_count=%d",
            seed,
            pb,
            c_before,
            reads,
            hold_end,
            max_cnt,
        )

        # Control: the same run barks once the petted count reaches pb.
        while True:
            st = await self._rd(INTR_STATE)
            cnt = await self._rd(WDOG_COUNT)
            if st & BARK_BIT:
                break
            _late("no bark after the pet")
        if cnt < pb - a:
            raise AssertionError(
                f"CTRL-MISSING CHK-WDT-PET-HOLD: seed={seed} bark with count 0x{cnt:x} < "
                f"pb - A ({pb} - {a})"
            )
        await self._wr(WDOG_CTRL, 0)
        await self._wr(INTR_STATE, BARK_BIT)
        self.logger.info("CTL-WDT-PET-BARK: seed=%d bark=1 count=%d pb=%d", seed, cnt, pb)

    async def _thold_zero(self) -> None:
        """CHK-WDT-THOLD-ZERO, control CTL-WDT-THOLD-ZERO."""
        dut = cocotb.top
        seed = self.tcfg.seed
        a = COUNT_ALLOW
        await self._wdt_baseline(0, WDOG_FAR_BITE, 0, graded=True)
        await self._wait_wdt(WDT_WAIT)
        st0 = await self._rd(INTR_STATE)
        if st0 & BARK_BIT:
            raise AssertionError(
                f"CTRL-MISSING CHK-WDT-THOLD-ZERO: seed={seed} bark set with the watchdog "
                f"disabled (INTR_STATE=0x{st0:x})"
            )
        self.logger.info("CTL-WDT-THOLD-ZERO: seed=%d enable=0 bark_thold=0 bark=0", seed)
        await self._wr(WDOG_CTRL, WDOG_EN)
        await self._poll_eq("WDOG_CTRL", WDOG_CTRL, WDOG_EN, WDOG_CTRL_FIELDS, "CHK-WDT-THOLD-ZERO")
        await ClockCycles(dut.clk_wdt_i, 1 + a)
        st1 = await self._rd(INTR_STATE)
        line = f"seed={seed} bark_thold=0 enable=1 wait_periods={1 + a} INTR_STATE=0x{st1:x}"
        if not (st1 & BARK_BIT):
            raise AssertionError(f"CHK-WDT-THOLD-ZERO FAIL: no bark: {line}")
        self.logger.info("CHK-WDT-THOLD-ZERO PASS: %s bark=1", line)
        await self._wr(WDOG_CTRL, 0)
        await self._poll_eq("WDOG_CTRL", WDOG_CTRL, 0, WDOG_CTRL_FIELDS, "CHK-WDT-THOLD-ZERO")
        await self._wr(INTR_STATE, BARK_BIT)
        await self._poll_eq("INTR_STATE", INTR_STATE, 0, BARK_BIT, "CHK-WDT-THOLD-ZERO")

    async def _thold_below(self) -> None:
        """CHK-WDT-THOLD-BELOW for the bark and then the bite, control CTL-WDT-THOLD-BELOW.

        Each threshold is written at or below a count read taken before the
        write; the count only rises, so the threshold is at or below the count
        when the write lands. The read-back of the threshold follows the landing
        (theory_of_operation.md:27-28). One clk_wdt_i period later the compare
        holds on a tick; ``A`` more periods cover the crossing to the status, as
        CHK-WDT-BARK-TIME grades on every run. The bite request is the
        ``wdt_timer_rst_req_o`` port.
        """
        dut = cocotb.top
        cfg = self.tcfg
        seed = cfg.seed
        a = COUNT_ALLOW
        await self._wdt_baseline(WDOG_FAR_BARK, WDOG_FAR_BITE, 0, graded=True)
        await self._wr(WDOG_CTRL, WDOG_EN)
        start = self.pins.count["clk_wdt_i"]
        cnt = 0
        while cnt < cfg.below_c:
            cnt = await self._rd(WDOG_COUNT)
            if self.pins.count["clk_wdt_i"] - start > 16 * cfg.below_c + 512:
                raise AssertionError(
                    f"CHK-WDT-THOLD-BELOW FAIL: seed={seed} count never reached "
                    f"{cfg.below_c} (last 0x{cnt:x})"
                )
        for ev, addr, off in (
            ("bark", WDOG_BARK_THOLD, cfg.below_off),
            ("bite", WDOG_BITE_THOLD, cfg.bite_off),
        ):
            c_read = await self._rd(WDOG_COUNT)
            st = await self._rd(INTR_STATE)
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            req = self.rd(dut.wdt_timer_rst_req_o)
            await RisingEdge(dut.clk_i)
            before = int(bool(st & BARK_BIT)) if ev == "bark" else req
            if before:
                raise AssertionError(
                    f"CTRL-MISSING CHK-WDT-THOLD-BELOW: seed={seed} {ev} already set before "
                    f"the threshold write (count 0x{c_read:x})"
                )
            thr = c_read - off
            name = "WDOG_BARK_THOLD" if ev == "bark" else "WDOG_BITE_THOLD"
            await self._wr(addr, thr)
            await self._poll_eq(name, addr, thr, AON[name][1], "CHK-WDT-THOLD-BELOW")
            await ClockCycles(dut.clk_wdt_i, 1 + a)
            if ev == "bark":
                st1 = await self._rd(INTR_STATE)
                got = int(bool(st1 & BARK_BIT))
            else:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                got = self.rd(dut.wdt_timer_rst_req_o)
                await RisingEdge(dut.clk_i)
            line = (
                f"seed={seed} event={ev} count_before_write=0x{c_read:x} threshold=0x{thr:x} "
                f"offset={off} before=0 wait_periods={1 + a} after={got}"
            )
            if got != 1:
                raise AssertionError(f"CHK-WDT-THOLD-BELOW FAIL: {line}")
            self.logger.info("CHK-WDT-THOLD-BELOW PASS: %s", line)
        self.logger.info("CTL-WDT-THOLD-BELOW: seed=%d bark=0 bite=0 before each write", seed)
        # The bite request holds until the cold reset (watchdog.adoc, Bark Interrupt
        # and Bite Reset); recover with the graded window closed.
        self._gate(False)
        await self.pulse_rst_ni(hold_cycles=PULSE_CYCLES, release_bound=RESET_BOUND)
        self._gate(True)

    async def _leg_p(self) -> None:
        await self._pet()
        await self._thold_zero()
        await self._thold_below()

    # -- leg K ------------------------------------------------------------------

    def _widx(self) -> int:
        """The ``clk_wdt_i`` rising-edge index at the pin now."""
        return self.pins.count["clk_wdt_i"]

    async def _wk_step(self, old: int, new: int, i_ref: int, due: int, chk: str, tag: str) -> dict:
        """Read ``WKUP_COUNT_LO`` back to back until it steps from ``old`` to ``new``.

        Returns the issue time and ``clk_wdt_i`` edge index of the last read of
        ``old`` (``s_o``, ``i_s``), the completion time and edge index of the first
        read of ``new`` (``d_n``, ``i_d``) and the reads. A first read of ``new``
        means the step came before the poll window; any other value, or no step
        within PRESC_LATE periods after ``due`` edges from ``i_ref``, fails.
        """
        seed = self.tcfg.seed
        s_old = i_old = None
        n = 0
        while True:
            i_s = self._widx()
            v, s, d = await self._timed_rd(WKUP_COUNT_LO)
            i_d = self._widx()
            n += 1
            if v == new:
                if s_old is None:
                    raise AssertionError(
                        f"{chk} FAIL: seed={seed} {tag}: the first poll read is already "
                        f"{new}; the count stepped before the poll window"
                    )
                return {"s_o": s_old, "i_s": i_old, "d_n": d, "i_d": i_d, "reads": n}
            if v != old:
                raise AssertionError(
                    f"{chk} FAIL: seed={seed} {tag}: WKUP_COUNT_LO read 0x{v:x}, expected "
                    f"{old} or {new}"
                )
            s_old, i_old = s, i_s
            if i_d - i_ref > due + PRESC_LATE:
                raise AssertionError(
                    f"{chk} FAIL: seed={seed} {tag}: no step to {new} within "
                    f"{due + PRESC_LATE} clk_wdt_i periods"
                )

    async def _leg_k(self) -> None:
        """Wakeup timer at prescaler 4095 with threshold 0, and the restart write."""
        dut = cocotb.top
        cfg = self.tcfg
        seed = cfg.seed
        a = COUNT_ALLOW
        per = PRESC_MAX + 1
        ctrl = PRESC_MAX << WKUP_PRESC_LSB
        await self._wr(WKUP_CTRL, ctrl)
        await self._poll_eq("WKUP_CTRL", WKUP_CTRL, ctrl, WKUP_CTRL_FIELDS, "CHK-WKUP-PRESC-MAX")
        for name in ("WKUP_THOLD_HI", "WKUP_THOLD_LO", "WKUP_COUNT_LO", "WKUP_COUNT_HI"):
            await self._wr(AON[name][0], 0)
            await self._poll_eq(name, AON[name][0], 0, AON[name][1], "CHK-WKUP-PRESC-MAX")
        await self._wr(INTR_STATE, WKUP_BIT)
        await self._poll_eq("INTR_STATE", INTR_STATE, 0, WKUP_BIT, "CHK-WKUP-THOLD-ZERO")
        await self._wr(WKUP_CAUSE, 0)
        await self._poll_eq("WKUP_CAUSE", WKUP_CAUSE, 0, CAUSE_FIELD, "CHK-WKUP-THOLD-ZERO")

        t_en = self._now()
        i_en = self._widx()
        await self._wr(WKUP_CTRL, ctrl | WKUP_EN)
        await self._poll_eq(
            "WKUP_CTRL", WKUP_CTRL, ctrl | WKUP_EN, WKUP_CTRL_FIELDS, "CHK-WKUP-PRESC-MAX"
        )
        t_en_rb = self._now()
        await ClockCycles(dut.clk_wdt_i, per - PRESC_EARLY)
        st0 = await self._rd(INTR_STATE)
        cause0, _s, d_pair = await self._timed_rd(WKUP_CAUSE)
        e_pair = self._edges("clk_wdt_i", t_en, d_pair)
        if e_pair > per:
            raise AssertionError(
                f"CTRL-MISSING CHK-WKUP-THOLD-ZERO: seed={seed} the early status and cause "
                f"reads completed {e_pair} clk_wdt_i periods after the enable write, above {per}"
            )
        self.logger.info(
            "CTL-WKUP-THOLD-ZERO: seed=%d early_reads_E=%d status=%d cause=%d",
            seed,
            e_pair,
            int(bool(st0 & WKUP_BIT)),
            cause0 & CAUSE_FIELD,
        )
        if (st0 & WKUP_BIT) or (cause0 & CAUSE_FIELD):
            raise AssertionError(
                f"CHK-WKUP-THOLD-ZERO FAIL: seed={seed} expired status {int(bool(st0 & WKUP_BIT))}"
                f" cause {cause0 & CAUSE_FIELD} at E={e_pair} <= {per} periods after the enable "
                "write, before the first prescaler completion"
            )
        st_1 = await self._wk_step(0, 1, i_en, per, "CHK-WKUP-THOLD-ZERO", "enable")
        d1n = st_1["d_n"]
        await ClockCycles(dut.clk_wdt_i, a)
        st1 = await self._rd(INTR_STATE)
        cause1 = await self._rd(WKUP_CAUSE)
        line = (
            f"seed={seed} prescaler={PRESC_MAX} thold=0 early_E={e_pair} early_status=0 "
            f"early_cause=0 status_after_step={int(bool(st1 & WKUP_BIT))} "
            f"cause_after_step={cause1 & CAUSE_FIELD} wait_periods={a}"
        )
        if not ((st1 & WKUP_BIT) and (cause1 & CAUSE_FIELD)):
            raise AssertionError(f"CHK-WKUP-THOLD-ZERO FAIL: not set at the first step: {line}")
        self.logger.info("CHK-WKUP-THOLD-ZERO PASS: %s", line)

        # Restart write with the same value, restart_gap periods after the step.
        await ClockCycles(dut.clk_wdt_i, cfg.restart_gap)
        t_w = self._now()
        i_w = self._widx()
        await self._wr(WKUP_CTRL, ctrl | WKUP_EN)
        await self._poll_eq(
            "WKUP_CTRL", WKUP_CTRL, ctrl | WKUP_EN, WKUP_CTRL_FIELDS, "CHK-WKUP-RESTART"
        )
        t_w_rb = self._now()
        await ClockCycles(dut.clk_wdt_i, per - PRESC_EARLY)
        st_2 = await self._wk_step(1, 2, i_w, per, "CHK-WKUP-RESTART", "restart")
        e_restart = self._edges("clk_wdt_i", d1n, st_2["s_o"])
        line = (
            f"seed={seed} restart_gap={cfg.restart_gap} E_first_step_to_last_old_read="
            f"{e_restart} period={per}"
        )
        if e_restart < per:
            raise AssertionError(f"CHK-WKUP-RESTART FAIL: {line}")
        self.logger.info("CHK-WKUP-RESTART PASS: %s count=1_after_one_period", line)
        # The step after each write against the write landing: the landing lies
        # between the write and its read-back, so this bracket is wider than one
        # period of difference and is logged, not graded.
        self.logger.info(
            "WKUP-STEP-AFTER-WRITE LOG: seed=%d enable=[%d,%d) restart=[%d,%d) period=%d",
            seed,
            self._edges("clk_wdt_i", t_en_rb, st_1["s_o"]),
            self._edges("clk_wdt_i", t_en, st_1["d_n"]),
            self._edges("clk_wdt_i", t_w_rb, st_2["s_o"]),
            self._edges("clk_wdt_i", t_w, st_2["d_n"]),
            per,
        )

        # CHK-WKUP-PRESC-MAX: N = PRESC_RUN count steps from the step to 2 to the
        # step to 2 + N. Each step lies at an edge between the issue of the last
        # read of the old count and the end of the first read of the new count;
        # the edge indices are taken at the pin before and after each read, so a
        # step is known to within u = i_d - i_s edges (two back-to-back reads plus
        # one edge for an index taken in the time step of an edge). The N steps
        # take E edges with i_s2 - i_d1 - 1 <= E <= i_d2 - i_s1 + 1, a bracket of
        # width u1 + u2 + 2. With that width below N, N x 4096 inside the bracket
        # excludes N x 4095 and N x 4097.
        due = PRESC_RUN * per
        i_mark = st_2["i_d"]
        await ClockCycles(dut.clk_wdt_i, due - PRESC_EARLY - (self._widx() - i_mark))
        st_3 = await self._wk_step(
            1 + PRESC_RUN, 2 + PRESC_RUN, i_mark, due, "CHK-WKUP-PRESC-MAX", "run"
        )
        e_lo = st_3["i_s"] - st_2["i_d"] - 1
        e_hi = st_3["i_d"] - st_2["i_s"] + 1
        u1 = st_2["i_d"] - st_2["i_s"]
        u2 = st_3["i_d"] - st_3["i_s"]
        width = e_hi - e_lo
        line = (
            f"seed={seed} prescaler={PRESC_MAX} N={PRESC_RUN} expected={due} "
            f"edges_bracket=[{e_lo},{e_hi}] width={width} u_first={u1} u_last={u2} "
            f"mid_error={(e_lo + e_hi) / 2 - due:+.1f} bound={PRESC_RUN / 2}"
        )
        if width >= PRESC_RUN:
            raise AssertionError(
                f"CTRL-MISSING CHK-WKUP-PRESC-MAX: bracket width not below N: {line}"
            )
        if not (e_lo <= due <= e_hi):
            raise AssertionError(f"CHK-WKUP-PRESC-MAX FAIL: {line}")
        self.logger.info("CHK-WKUP-PRESC-MAX PASS: %s", line)

        await self._wkup_stop()
        await self._wr(WKUP_CAUSE, 0)
        await self._poll_eq("WKUP_CAUSE", WKUP_CAUSE, 0, CAUSE_FIELD, "CHK-WKUP-THOLD-ZERO")

    async def _leg_carry(self) -> None:
        """CHK-WKUP-CARRY-READ, control CTL-WKUP-CARRY, at prescaler 0.

        With prescaler 0 the count rises by one per clk_wdt_i period after the
        enable write lands. A read returns a copy of the count taken at or
        before the read, which may lag the live count by up to A counts. So the
        count of a read is within
        [pre + E(read-back, issue) - 1 - A, pre + E(enable write, completion)].
        The upper bounds take no allowance: a lagging copy is never above the
        live count.
        """
        dut = cocotb.top
        seed = self.tcfg.seed
        chk = "CHK-WKUP-CARRY-READ"
        pre = (1 << 32) | ((1 << 32) - CARRY_MARGIN)
        await self._wr(WKUP_CTRL, 0)
        await self._poll_eq("WKUP_CTRL", WKUP_CTRL, 0, WKUP_CTRL_FIELDS, chk)
        for name, val in (
            ("WKUP_THOLD_HI", M32),
            ("WKUP_THOLD_LO", M32),
            ("WKUP_COUNT_LO", pre & M32),
            ("WKUP_COUNT_HI", pre >> 32),
        ):
            await self._wr(AON[name][0], val)
            await self._poll_eq(name, AON[name][0], val, AON[name][1], chk)
        t_en = self._now()
        await self._wr(WKUP_CTRL, WKUP_EN)
        await self._poll_eq("WKUP_CTRL", WKUP_CTRL, WKUP_EN, WKUP_CTRL_FIELDS, chk)
        t_rb = self._now()

        # programmers_guide.md:33-45, with a wait between the HI and LO reads that
        # puts the LO carry between them.
        hi1, _s, d_h = await self._timed_rd(WKUP_COUNT_HI)
        e_h = self._edges("clk_wdt_i", t_en, d_h)
        # The LO read waits A periods more, so even a copy that lags by A already
        # holds the carried count.
        await ClockCycles(dut.clk_wdt_i, CARRY_MARGIN + 1 + COUNT_ALLOW)
        lo, s_l, d_l = await self._timed_rd(WKUP_COUNT_LO)
        hi2 = await self._rd(WKUP_COUNT_HI)
        lo2, s_l2, d_l2 = lo, s_l, d_l
        if hi1 != hi2:
            lo2, s_l2, d_l2 = await self._timed_rd(WKUP_COUNT_LO)
        result = (hi2 << 32) | lo2
        naive = (hi1 << 32) | lo
        e_l_lo = self._edges("clk_wdt_i", t_rb, s_l)
        if e_h >= CARRY_MARGIN or e_l_lo - 1 - COUNT_ALLOW < CARRY_MARGIN:
            raise AssertionError(
                f"CTRL-MISSING {chk}: seed={seed} HI read done E={e_h} (need < {CARRY_MARGIN}) "
                f"LO read issued E={e_l_lo} after the read-back (need > {CARRY_MARGIN} + A {COUNT_ALLOW})"
            )
        self.logger.info(
            "CTL-WKUP-CARRY: seed=%d hi_read_E=%d lo_read_E=%d carry_between=1",
            seed,
            e_h,
            e_l_lo,
        )
        lo_min = e_l_lo - 1 - COUNT_ALLOW - CARRY_MARGIN
        lo_max = self._edges("clk_wdt_i", t_en, d_l) - CARRY_MARGIN
        r_min = pre + self._edges("clk_wdt_i", t_rb, s_l2) - 1 - COUNT_ALLOW
        r_max = pre + self._edges("clk_wdt_i", t_en, d_l2)
        line = (
            f"seed={seed} preload=0x{pre:x} hi=0x{hi1:x} lo=0x{lo:x} lo_bounds=[{lo_min},"
            f"{lo_max}] naive=0x{naive:x} hi2=0x{hi2:x} lo2=0x{lo2:x} result=0x{result:x} "
            f"result_bounds=[0x{r_min:x},0x{r_max:x}] allow={COUNT_ALLOW} "
            f"lag_lo={e_l_lo - 1 - CARRY_MARGIN - lo}"
        )
        clauses = (
            ("hi1", hi1 == 1),
            ("lo_bounds", lo_min <= lo <= lo_max),
            ("naive", naive < (2 << 32)),
            ("hi2", hi2 == 2),
            ("result_bounds", r_min <= result <= r_max),
            ("naive_lt_result", naive < result),
        )
        failed = [name for name, held in clauses if not held]
        if failed:
            raise AssertionError(f"{chk} FAIL: {line} failed={','.join(failed)}")
        self.logger.info("%s PASS: %s", chk, line)
        await self._wkup_stop()

    # -- leaf -------------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        vcs = "vcs" in cocotb.SIM_NAME.lower()
        # The dbg_rstb_i cell of CHK-REGWEN-HOLD runs on VCS on the full-CPU build only,
        # selected from the build the leaf runs on (the stub CPU has no load on the pin).
        full_cpu = self.full_cpu_build()
        self.dbg_cell = vcs and full_cpu
        self.n_dbg = 0
        # The full-CPU testlist entry passes +sep_require_full_cpu: there the dbg_rstb_i
        # cell is required, so a build or simulator without it fails the leaf.
        if "sep_require_full_cpu" in cocotb.plusargs and not self.dbg_cell:
            msg = (
                "CTL-FULL-CPU FAIL: +sep_require_full_cpu needs the VCS full-CPU build for the "
                f"dbg_rstb_i cell (full_cpu={int(full_cpu)} vcs={int(vcs)})"
            )
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info(
            "OBS-DBG-EVENT: build=%s tool=%s dbg_rstb_i_cell=%s reason=%s",
            "full_cpu" if full_cpu else "cpu_stub",
            "vcs" if vcs else "verilator",
            "run" if self.dbg_cell else "skipped",
            "VCS full-CPU build"
            if self.dbg_cell
            else ("no dbg_rstb_i load on this build" if not full_cpu else "VCS only"),
        )
        self.sys_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        self.tcfg = cfg = _Cfg(seed, self.sys_ps, dbg_cell=self.dbg_cell)
        self.logger.info(
            "DRAW clocks ratios=%s ref_phase_ps=%s wdt_phase_ps=%d P_w=%d",
            cfg.ratios,
            cfg.ref_phase_ps,
            cfg.wdt_phase_ps,
            P_W,
        )
        self.logger.info(
            "DRAW leg_r walk_gaps=%s W_lo=0x%016x W_hi=0x%016x reload_order=%s",
            cfg.walk_gaps,
            cfg.w_lo,
            cfg.w_hi,
            cfg.reload_order,
        )
        self.logger.info(
            "DRAW leg_t b=%d d=%d b2=%d bm=0x%x dm=0x%x", cfg.b, cfg.d, cfg.b2, cfg.bm, cfg.dm
        )
        self.logger.info(
            "DRAW leg_w presc_order=%s p_m=%d p_m_order=%s Ts=%d g=%d r=%d",
            cfg.presc,
            cfg.p_m,
            cfg.p_m_order,
            cfg.ts,
            cfg.g,
            cfg.r,
        )
        self.logger.info(
            "DRAW leg_s walk_order=%s walk_one=%s coh_bark=0x%x coh_bite=0x%x read_gaps=%s",
            cfg.walk_order,
            {k: hex(v) for k, v in cfg.walk_one.items()},
            cfg.coh_bark,
            cfg.coh_bite,
            cfg.read_gaps,
        )
        self.logger.info(
            "DRAW leg_l Xb=0x%x Xd=0x%x Xh=0x%x Xl=0x%x locked=0x%x,0x%x events=%s repeat=%d "
            "cold_bark=0x%x",
            cfg.xb,
            cfg.xd,
            cfg.xh,
            cfg.xl,
            cfg.locked_b,
            cfg.locked_d,
            cfg.events,
            cfg.repeat,
            cfg.cold_bark,
        )
        self.logger.info(
            "DRAW leg_p_k scope_flips=0x%x,0x%x,0x%x,%s pb=%d pet_at=%d below_c=%d "
            "below_off=%d bite_off=%d restart_gap=%d",
            cfg.scope_ctrl_flip,
            cfg.scope_count_flip,
            cfg.scope_presc_flip,
            [hex(v) for v in cfg.scope_wk_flip],
            cfg.pb,
            cfg.pet_at,
            cfg.below_c,
            cfg.below_off,
            cfg.bite_off,
            cfg.restart_gap,
        )
        self.logger.info(
            "TIMER env: a=%d A=%d P_w=%d rate_wait_ref=%d poll_reads=%d "
            "arm_bound_ref=%d ref_settle=%d wdt_wait=%d reset_bound=%d ovrd_cycles=%d dbg_event=%s",
            EDGE_ALLOW,
            COUNT_ALLOW,
            P_W,
            RATE_WAIT_REF,
            POLL_READS,
            REFCNT_ARM_REF,
            REF_SETTLE,
            WDT_WAIT,
            RESET_BOUND,
            OVRD_CYCLES,
            "run" if self.dbg_cell else "skipped (VCS full-CPU build only)",
        )

        k0 = cfg.ratios[0]
        self.cfg.ref_clk_period_ns = k0 * self.cfg.sys_clk_period_ns
        self.cfg.wdt_clk_period_ns = P_W * self.cfg.sys_clk_period_ns
        self.clock_phases_ps = {
            "clk_ref_i": cfg.ref_phase_ps[0],
            "clk_wdt_i": cfg.wdt_phase_ps,
        }
        self.pins = SepPinEdgeCounter(("clk_i", "clk_ref_i", "clk_wdt_i"), keep=1 << 16).start()
        self.rst_timer = SepEdgeTimer(cocotb.top.rst_ni, name="rst_ni").start()
        await self.bring_up_no_cpu()
        await self._wait_high(cocotb.top.dbg_sep_reset_n_o, "dbg_sep_reset_n_o")
        self.wdt = SepWdtAon(self)
        self.swrst = SepSwReset(self)

        self._gate(True)
        await self._leg_r()
        await self._leg_t()
        await self._leg_w()
        await self._leg_s()
        await self._leg_l()
        await self._leg_p()
        await self._leg_k()
        await self._leg_carry()
        self._gate(False)
        self.result_pass(TEST, seed, len(self.required_evidence))
