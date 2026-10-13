# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""REFERENCE_COUNTER, the watchdog and wakeup timers, the timer bus shape and WDOG_REGWEN.

no_cpu on ``lsu_stub_all_live`` with ``+skip_fuse_sense`` and
``+sep_edn_jtag_reset_waive`` (the ``sep_reset_n`` override pulse of leg L
resets the crypto engines without isolation). Five legs run in one leaf, in
this order, over the CPU-LSU master on ``s_axi``:

* Leg R. ``REFERENCE_COUNTER`` counts ``clk_ref_i`` edges at five clock ratios
  ``k`` of {2, 3, 5, 8, 13} in a drawn order; a 64-bit write reloads it with
  and without a carry into the high word; a cold reset restarts it
  (``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``, ``REFERENCE_COUNTER``;
  ``hw/sys/sep/doc/clk_rst.adoc``, Clock Distribution).
* Leg T. The bark status and the bite request follow the count reads that
  reach the bark and bite thresholds, a larger bark threshold barks later in
  count, thresholds near 2^32 do not wrap, and ``INTR_TEST`` forces the bark
  status without a bite (``hw/sys/sep/doc/watchdog.adoc``, Bark Interrupt and
  Bite Reset; ``aon_timer.adoc``).
* Leg W. The wakeup expiry follows the 64-bit threshold across the 32-bit
  boundary at prescaler 0, 1 and a drawn value of 2 to 15, with both half
  orders, and a larger threshold expires later in count.
* Leg S. The watchdog registers answer 32-bit accesses on either lane with the
  value their access type gives; ``WDOG_COUNT`` reads never fall while counting.
* Leg L. ``WDOG_REGWEN`` stays 0 after a write of 1, and ``regwen`` and the four
  thresholds keep their values over ``wdt_rst_ni``, ``dbg_rstb_i`` (VCS, full-CPU build only), a
  software engine reset and a ``sep_reset_n`` override; only the cold reset
  restores the defaults (``hw/sys/sep/doc/clk_rst.adoc``, Reset Architecture).

``aon_timer.adoc`` is
``vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/gen/adoc/aon_timer.adoc``.
Expected values come from the register description (generated register
metadata) and the written values, never from a DUT read. The count unit of
``WDOG_COUNT`` is not stated, so the watchdog and wakeup checks grade count
relations only. Environment choices (logged): the edge allowance ``a`` of leg R,
the count allowance ``A`` of legs T and W, the clock period ``P_w`` of
``clk_wdt_i``, poll bounds and wait lengths.

Checkers: CHK-REFCNT-RATE, CHK-REFCNT-PHASE, CHK-REFCNT-WRITE,
CHK-REFCNT-RESET, CHK-WDT-ORDER, CHK-WDT-THOLD-MONO, CHK-WDT-MAX,
CHK-WDT-INTRTEST, CHK-WDT-ALERT-ACCESS, CHK-WKUP-WIDE, CHK-WKUP-LATER,
CHK-WDT-SHAPE, CHK-WDT-COHERENT, CHK-REGWEN-STICKY, CHK-REGWEN-HOLD,
CHK-REGWEN-COLD. Controls (not counted): CTL-WDT-ENABLE, CTL-WDT-THOLD,
CTL-WDT-PAUSE, CTL-WKUP-SMALL, CTL-WKUP-CAUSE, CTL-REGWEN-LOCKED.

The graded window (owner code of this test) opens at leg R and closes for the
enable control run, the small wakeup control runs and the recovery reset of a
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
SHAPE_GRADED = ("WKUP_CTRL", "WKUP_COUNT_HI", "WKUP_COUNT_LO")

# Environment choices (logged; the specification gives no tolerance).
RATIOS = (2, 3, 5, 8, 13)
P_W = 8  # clk_wdt_i period in clk_i periods
EDGE_ALLOW = 2  # a: clk_ref_i edges
COUNT_ALLOW = 4  # A: clk_wdt_i counts
RATE_WAIT_REF = 400  # clk_ref_i periods between the two rate reads
BARK_PASSES = 4  # passes after a count read at or above the bark threshold
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
            passes.append({"bark": int(bool(st & BARK_BIT)), "bite": bite, "count": cnt, "t": t_st})
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
        prev = c0
        bark_pass = bite_pass = None
        first_ge = None
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
            if first_ge is None and c >= bx:
                first_ge = i
            if bark_pass is None and p["bark"]:
                bark_pass = i
            if bite_pass is None and p["bite"]:
                bite_pass = i
        assert bark_pass is not None and bite_pass is not None
        assert first_ge is not None and bark_pass <= first_ge + BARK_PASSES, (
            f"{chk} FAIL: run={tag} bark set at pass {bark_pass}, more than {BARK_PASSES} "
            f"passes after the count first read >= bx at pass {first_ge}"
        )
        return {
            "count_at_bark": passes[bark_pass]["count"],
            "count_at_bite": passes[bite_pass]["count"],
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
            "bark_early=0 bite_with_bark_clear=0 bite_early=0 count_at_bite=%d passes=%d",
            b,
            d,
            COUNT_ALLOW,
            rb["count_at_bark"],
            rb["count_at_bite"],
            len(base["passes"]),
        )
        ps = base["passes"]
        self.logger.info(
            "OBS-WDT-RATE: dcount=%d E_wdt=%d",
            ps[-1]["count"] - ps[0]["count"],
            self._edges("clk_wdt_i", ps[0]["t"], ps[-1]["t"]),
        )

        # Larger bark threshold.
        larger = await self._wdt_run(b2, d2, 0, "CHK-WDT-ORDER")
        self._precondition(larger, min_gap, "larger")
        rl = self._grade_order(larger, b2, d2, 0, "CHK-WDT-ORDER", "larger")
        self.logger.info(
            "CHK-WDT-ORDER PASS: run=larger bark=%d bite=%d allowance=%d count_at_bark=%d "
            "bark_early=0 bite_with_bark_clear=0 bite_early=0 count_at_bite=%d passes=%d",
            b2,
            d2,
            COUNT_ALLOW,
            rl["count_at_bark"],
            rl["count_at_bite"],
            len(larger["passes"]),
        )
        c1, c2 = rb["count_at_bark"], rl["count_at_bark"]
        line = (
            f"b={b} count_at_bark={c1} b2={b2} count_at_bark2={c2} allowance={COUNT_ALLOW} "
            f"later={int(c2 > c1)}"
        )
        assert c2 >= b2 - COUNT_ALLOW and c2 > c1, f"CHK-WDT-THOLD-MONO FAIL: {line}"
        self.logger.info("CHK-WDT-THOLD-MONO PASS: %s", line)
        self.logger.info(
            "OBS-WDT-BARK-TIME: base_ps=%d larger_ps=%d",
            rb["t_bark"] - base["t_en"],
            rl["t_bark"] - larger["t_en"],
        )

        # Thresholds near 2^32.
        mx = await self._wdt_run(bm, dm, bm - 32, "CHK-WDT-MAX")
        self._precondition(mx, min_gap, "max")
        rm = self._grade_order(mx, bm, dm, bm - 32, "CHK-WDT-MAX", "max")
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
        samples = {"high": 0, "n": 0}
        stop = {"v": False}

        async def _watch() -> None:
            while not stop["v"]:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                samples["n"] += 1
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
        stop["v"] = True
        await RisingEdge(dut.clk_i)
        if not watch.done():
            watch.cancel()
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

    async def _wkup_count(self) -> int:
        for _ in range(4):
            hi = await self._rd(WKUP_COUNT_HI)
            lo = await self._rd(WKUP_COUNT_LO)
            hi2 = await self._rd(WKUP_COUNT_HI)
            if hi == hi2:
                return (hi << 32) | lo
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
            await self._poll_eq(name, addr, val, M32, "CHK-WKUP-WIDE")
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
            cnt = await self._wkup_count()
            passes.append({"st": int(bool(st & WKUP_BIT)), "count": cnt, "t": t_st})
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

    def _grade_wide(self, run: dict, thr: int, tag: str) -> None:
        for i, x in enumerate(run["passes"]):
            if x["st"] and x["count"] < thr - COUNT_ALLOW:
                raise AssertionError(
                    f"CHK-WKUP-WIDE FAIL: run={tag} status set at pass {i} with count "
                    f"0x{x['count']:x} < thr - A (thr=0x{thr:x} A={COUNT_ALLOW})"
                )

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
                self._grade_wide(run, thr, f"p={p} run{k}")
                assert run["status_before"] == 0
                self.logger.info(
                    "CHK-WKUP-WIDE PASS: p=%d run=%d class=CROSS32 thr=0x%x_%08x preload=0x%x_%08x "
                    "allowance=%d status_before=0 count_at_expiry=0x%x passes=%d half_order=%s",
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
                )
                runs.append(run)
                await self._wkup_stop()
            n1, n2 = runs[0]["n"], runs[1]["n"]
            self.logger.info("OBS-WKUP-TIME: p=%d t1=%d t2=%d", p, runs[0]["t"], runs[1]["t"])
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
        await self._wr(WKUP_CAUSE, 0)
        after = await self._poll_eq("WKUP_CAUSE", WKUP_CAUSE, 0, CAUSE_FIELD, "CTL-WKUP-CAUSE")
        self.logger.info(
            "CTL-WKUP-CAUSE: before_clear=%d after_clear=%d", cause & 1, after & CAUSE_FIELD
        )

        n_checks = 0
        lanes = set()
        differs = {name: False for name in SHAPE_GRADED}
        for pi in range(4):
            for name in cfg.walk_order:
                addr, mask, reset = AON[name]
                pat = cfg.patterns(name)[pi]
                wv = pat & ~WKUP_EN if name == "WKUP_CTRL" else pat
                await self._wr(addr, wv)
                got = await self._poll_eq(name, addr, wv, mask, "CHK-WDT-SHAPE")
                lane = "hi" if addr & 0x4 else "lo"
                fc = field_compare(got, wv, mask)
                if name in SHAPE_GRADED:
                    lanes.add(lane)
                    n_checks += 1
                    differs[name] |= (got & mask) != (reset & mask)
                    self.logger.info("WDT-SHAPE LOG: reg=%s lane=%s %s", name, lane, fc.fields())
                else:
                    self.logger.info(
                        "CTL-WDT-THOLD: reg=%s lane=%s pattern=0x%08x readback=0x%08x "
                        "timer=disabled",
                        name,
                        lane,
                        wv,
                        got,
                    )
            # WKUP_CAUSE (RW0C): a write cannot set it.
            pat = cfg.patterns("WKUP_CAUSE")[pi]
            await self._wr(WKUP_CAUSE, pat)
            await self._wait_wdt(16)
            got = await self._rd(WKUP_CAUSE)
            fc = field_compare(got, 0, CAUSE_FIELD)
            assert fc.ok, (
                f"CHK-WDT-SHAPE FAIL: WKUP_CAUSE set by a write of 0x{pat:x}: {fc.fields()}"
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
            len(SHAPE_GRADED) + 4,
            n_checks,
        )

        # Coherent count reads.
        await self._wr(WDOG_COUNT, 0)
        await self._poll_eq("WDOG_COUNT", WDOG_COUNT, 0, M32, "CHK-WDT-COHERENT")
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
                    got = await self._poll_eq(name, AON[name][0], val, M32, "CHK-WDT-COHERENT")
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
        await self._poll_eq("WDOG_COUNT", WDOG_COUNT, 0x1000, M32, "CHK-WDT-COHERENT")
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
            # module; the debug reset input of the CPU core must read 0 in the pulse.
            load = dut.u_dut.u_sep.u_sep_cpu.u_el2_veer_wrapper.dbg_rst_l
            await RisingEdge(dut.clk_i)
            dut.dbg_rstb_i.value = 0
            await ClockCycles(dut.clk_i, PULSE_CYCLES)
            await ReadOnly()
            low = self.rd(load)
            await RisingEdge(dut.clk_i)
            dut.dbg_rstb_i.value = 1
            assert low == 0, "u_el2_veer_wrapper.dbg_rst_l did not fall during the dbg_rstb_i pulse"
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

    async def _leg_l(self) -> None:
        cfg = self.tcfg
        r0 = await self._rd(WDOG_REGWEN)
        assert r0 & REGWEN_FIELD, f"CHK-REGWEN-STICKY FAIL: regwen reads 0x{r0:x} before the clear"
        for name, val in zip(THOLD_REGS, (cfg.xb, cfg.xd, cfg.xh, cfg.xl)):
            await self._wr(AON[name][0], val)
            await self._poll_eq(name, AON[name][0], val, M32, "CHK-REGWEN-HOLD")
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
        await self.pulse_rst_ni(hold_cycles=PULSE_CYCLES, release_bound=RESET_BOUND)
        st = await self._read_lock_state()
        for name in ("WDOG_REGWEN",) + THOLD_REGS:
            fc = field_compare(st[name], AON[name][2], AON[name][1])
            assert fc.ok, f"CHK-REGWEN-COLD FAIL: reg={name} after the cold reset {fc.fields()}"
        await self._wr(WDOG_BARK_THOLD, cfg.cold_bark)
        await self._poll_eq(
            "WDOG_BARK_THOLD", WDOG_BARK_THOLD, cfg.cold_bark, M32, "CHK-REGWEN-COLD"
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
        assert armed == 5, f"CHK-REGWEN-COLD FAIL: armed_before={armed}/5"

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
            "TIMER env: a=%d A=%d P_w=%d rate_wait_ref=%d bark_passes=%d poll_reads=%d "
            "arm_bound_ref=%d ref_settle=%d wdt_wait=%d reset_bound=%d ovrd_cycles=%d dbg_event=%s",
            EDGE_ALLOW,
            COUNT_ALLOW,
            P_W,
            RATE_WAIT_REF,
            BARK_PASSES,
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
        self._gate(False)
        self.logger.info(
            "RESULT %s seed=%d PASS checks=%d", TEST, seed, len(self.required_evidence)
        )
