# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The AON timer wakeup counter, expiry status, watchdog pet and WDOG_REGWEN lock follow the spec.

no_cpu host-AXI CSR test of the SEP WDT aon_timer internals separate from the
bark/bite/NMI story: the WKUP (wakeup) timer + its INTR_STATE.wkup_expired RW1C
status, the WDOG counter advance + pet, and the WDOG_REGWEN config-lock. The WKUP
interrupt OUTPUT is unused in sep, so the expiry is proven via the polled
INTR_STATE.wkup_expired CSR bit (full RW1C clear) -- no ISR/NMI needed. The
test also grades the prescaler divide (CHK-WKUP-PRESCALE), the sticky
WKUP_CAUSE status (CHK-WKUP-CAUSE), INTR_TEST (CHK-INTR-TEST), the REGWEN lock
scope (CHK-REGWEN-SCOPE) and SEP_CPU_CTRL.REFERENCE_COUNTER (CHK-REFCNT-RUNS,
not an aon_timer register).

The graded coverage window of this leaf is open only around the two locked
threshold writes of CHK-REGWEN-LOCK and their readbacks; every other step runs
with it closed.

This test reads every counter frontdoor and clears with a full RW1C. Distinct from
cpu/sep_nmi_sanity_test (bark -> NMI) and cpu/sep_reset_wdt_sanity_test
(bark/pet/disable/re-bark and bite -> wdt_timer_rst_req_o): this test proves the
other aon_timer internals (WKUP timer, REGWEN config-lock, plain counter/pet),
not bark/bite/NMI.

This test runs clk_wdt at WDT_CLK_RATIO (8) core periods, so the counter waits
and poll budgets are sized in core cycles accordingly. The block is always
clocked (no CLOCK_GATE_CTRL ungate). Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import aon_timer_regwen_gates, aon_timer_wkup_ticks_per_count
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, WDT_TIMER
from seq_lib.sep_wdt_aon_seq import (
    INTR_STATE,
    INTR_TEST,
    INTR_TEST_WKUP_EXPIRED,
    INTR_WKUP_EXPIRED,
    INTR_WKUP_LSB,
    WDOG_BARK_THOLD,
    WDOG_BITE_THOLD,
    WDOG_COUNT,
    WDOG_CTRL,
    WDOG_ENABLE,
    WDOG_REGWEN,
    WKUP_CAUSE,
    WKUP_CAUSE_BIT,
    WKUP_CAUSE_LSB,
    WKUP_COUNT_HI,
    WKUP_COUNT_LO,
    WKUP_CTRL,
    WKUP_ENABLE,
    WKUP_PRESCALER_SHIFT,
    WKUP_THOLD_HI,
    WKUP_THOLD_LO,
    SepWdtAon,
    SepWdtCfg,
)

# How much faster than the silicon 1000x ratio we run clk_wdt for this CSR test
# (sim-timing knob): clk_wdt = WDT_CLK_RATIO x the core period -- still
# slower than the core (a valid CDC ratio) so the aon_timer clk_i->clk_aon register
# CDC (prim_reg_cdc busy-stall on a WKUP_CTRL/WDOG enable write) and the counters
# resolve within the AXI timeout, while still exercising the count/expiry/lock paths.
WDT_CLK_RATIO = 8

# clk_wdt ticks the free-running WDOG_COUNT must climb before the REGWEN-scope
# probe lowers it. A literal: it is the non-vacuity anchor for that check and
# must not move with any seeded value.
_COUNT_RUN_FLOOR = 40

TEST = "sep_wdt_aon_timer_internals_test"

# CHK-WKUP-PRESCALE window, in units of the divided count step: the window is
# _PRESCALE_STEPS_PER_P x P steps of P + 1 ticks. At that length a divisor of P
# gives at least two more counts than the read bound of the P + 1 divisor allows,
# and a divisor of 2 x (P + 1) gives about half the counts, so both fail.
_PRESCALE_STEPS_PER_P = 3

# CHK-WKUP-COUNT window in clk_wdt ticks (prescaler 0): the length difference
# of the two stopped runs.
_COUNT_WINDOW_TICKS = 60

# CHK-WDOG-PET window in clk_wdt ticks: the length difference of the two
# stopped watchdog runs.
_PET_WINDOW_TICKS = 1200

# Length in clk_wdt ticks of the shorter stopped run of each pair. It leaves
# room for the enable readback before the stop write.
_RUN_BASE_TICKS = 32

# CHK-WKUP-EXPIRE point legs (environment choices): each leg starts
# _EXPIRE_GUARD + 1 counts away from the start whose run would end on the
# threshold, and reads INTR_STATE and WKUP_CAUSE _EXPIRE_WAIT_TICKS clk_wdt
# ticks after its stopped count settles.
_EXPIRE_GUARD = 1
_EXPIRE_WAIT_TICKS = 64

# A stopped count is settled when two reads _SETTLE_TICKS clk_wdt ticks apart
# agree; at most _SETTLE_POLLS reads follow the first (environment choices; the
# age of a count read is not stated).
_SETTLE_TICKS = 8
_SETTLE_POLLS = 8

# Generated field masks of the registers the lock legs grade. Both thresholds
# are one 32-bit field (aon_timer.hjson WDOG_BARK_THOLD / WDOG_BITE_THOLD,
# bits 31:0), so the field mask is the whole register word.
_REGWEN_MASK = WDT_TIMER.field_mask("WDOG_REGWEN", "regwen")
_BARK_MASK = WDT_TIMER.field_mask("WDOG_BARK_THOLD", "threshold")
_BITE_MASK = WDT_TIMER.field_mask("WDOG_BITE_THOLD", "threshold")

# Salt of the leaf's own draw stream for the WDOG_BITE_THOLD lock leg. A
# separate stream leaves every SepWdtCfg draw, and so every recorded seed,
# where it was.
_LOCK_DRAW_SALT = 0xB17E_10C4

# WDOG_BITE_THOLD draw range (an environment choice; the specification gives
# no value). The watchdog stays enabled through the lock legs and the
# REGWEN-scope probe, so the bite threshold is drawn far above any count those
# legs let the counter reach and above the SepWdtCfg bark draw range. The upper
# bound stays below the park value CHK-WDOG-PET writes, so the pre-lock write
# changes the register.
_BITE_DRAW_LO = 0x0010_0000
_BITE_DRAW_HI = 0x00F0_0000


class _LockDraws:
    """WDOG_BITE_THOLD values of the lock legs, from the leaf's salted stream.

    ``bite_postlock`` differs from ``bite_prelock`` by construction: it is drawn
    from the range with one value fewer and stepped over the pre-lock value.
    """

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed ^ _LOCK_DRAW_SALT)
        span = _BITE_DRAW_HI - _BITE_DRAW_LO
        self.bite_prelock = _BITE_DRAW_LO + rng.randrange(span)
        post = _BITE_DRAW_LO + rng.randrange(span - 1)
        if post >= self.bite_prelock:
            post += 1
        self.bite_postlock = post

    def summary(self) -> str:
        return f"bite_prelock=0x{self.bite_prelock:08x} bite_postlock=0x{self.bite_postlock:08x}"


# SEP_CPU_CTRL.REFERENCE_COUNTER is one 64-bit field. The high 32-bit AXI
# window is the last word of that field.
REFERENCE_COUNTER_LO = SEP_CPU_CTRL.addr("REFERENCE_COUNTER")
_RC_BITS = SEP_CPU_CTRL.field_width("REFERENCE_COUNTER", "rc")
if _RC_BITS % 32:
    raise RuntimeError(f"REFERENCE_COUNTER.rc is {_RC_BITS} bits, not a multiple of 32")
REFERENCE_COUNTER_HI = REFERENCE_COUNTER_LO + 4 * ((_RC_BITS // 32) - 1)


@pyuvm.test()
class sep_wdt_aon_timer_internals_test(sep_base_test):
    """WKUP timer (count + expiry RW1C), WDOG pet, and WDOG_REGWEN config-lock."""

    required_evidence = (
        "CHK-WKUP-COUNT",
        "CHK-WKUP-PRESCALE",
        "CHK-WKUP-EXPIRE",
        "CHK-WKUP-CAUSE",
        "CHK-INTR-TEST",
        "CHK-WDOG-PET",
        "CHK-REFCNT-RUNS",
        "CHK-NONVAC",
        "CHK-REGWEN-LOCK",
        "CHK-REGWEN-SCOPE",
    )

    async def _grade(self, ok: bool, chk: str, fail: str) -> None:
        """Close the graded window first, then raise ``<chk> FAIL``, on a failed check.

        The close waits for the next time step, so it never writes in a ReadOnly
        phase.
        """
        if not ok:
            await NextTimeStep()
            close_graded_window(self.logger)
            raise AssertionError(f"{chk} FAIL: {fail}")

    async def _poll_bit_set(
        self, addr: int, bit: int, *, timeout_cycles: int, step: int
    ) -> tuple[bool, int]:
        """Poll addr until (val>>bit)&1 == 1 or timeout; the caller grades it."""
        waited = 0
        val = 0
        while waited < timeout_cycles:
            val = await self.wdt.read(addr)
            if (val >> bit) & 1:
                return True, val
            await ClockCycles(cocotb.top.clk_i, step)
            waited += step
        return False, val

    async def _poll_bit_clear(
        self, addr: int, bit: int, *, timeout_cycles: int, step: int
    ) -> tuple[bool, int]:
        """Poll addr until (val>>bit)&1 == 0 or timeout (for AON-domain clears that
        settle over a few clk_wdt cycles via the register CDC)."""
        waited = 0
        val = 0
        while waited < timeout_cycles:
            val = await self.wdt.read(addr)
            if ((val >> bit) & 1) == 0:
                return True, val
            await ClockCycles(cocotb.top.clk_i, step)
            waited += step
        return False, val

    async def _poll_at_least(
        self, addr: int, floor: int, *, timeout_cycles: int, step: int
    ) -> tuple[bool, int]:
        """Poll addr until the read value is >= floor or timeout (for AON-domain
        writes that settle over a few clk_wdt cycles via the register CDC)."""
        waited = 0
        val = 0
        while waited < timeout_cycles:
            val = await self.wdt.read(addr)
            if val >= floor:
                return True, val
            await ClockCycles(cocotb.top.clk_i, step)
            waited += step
        return False, val

    async def _poll_at_most(
        self, addr: int, ceiling: int, *, timeout_cycles: int, step: int
    ) -> tuple[bool, int]:
        """Poll addr until the read value is <= ceiling or timeout. The mirror of
        _poll_at_least, for proving a write that LOWERS a free-running counter."""
        waited = 0
        val = 0
        while waited < timeout_cycles:
            val = await self.wdt.read(addr)
            if val <= ceiling:
                return True, val
            await ClockCycles(cocotb.top.clk_i, step)
            waited += step
        return False, val

    async def run_scenario(self) -> None:
        self.cfg_wdt = SepWdtCfg(self.random_seed())
        self.logger.info("WDT config: %s", self.cfg_wdt.summary())
        self.lock_draws = _LockDraws(self.cfg_wdt.seed)
        self.logger.info("WDT lock draws: %s", self.lock_draws.summary())
        # Speed clk_wdt for this CSR test (see WDT_CLK_RATIO). Set before bring-up so
        # start_clocks picks it up. _tick = core cycles per clk_wdt tick.
        self.cfg.wdt_clk_period_ns = WDT_CLK_RATIO * self.cfg.sys_clk_period_ns
        self._tick = WDT_CLK_RATIO
        self.logger.info(
            "WDT sim-timing knob: clk_wdt=%dns (%dx core), _tick=%d core cycles",
            self.cfg.wdt_clk_period_ns,
            WDT_CLK_RATIO,
            self._tick,
        )
        await self.bring_up_no_cpu()
        self.wdt = SepWdtAon(self)

        await self._chk_wkup_count()
        await self._chk_wkup_prescale()
        await self._chk_wkup_expire()
        await self._chk_wkup_expire_point()
        await self._chk_intr_test()
        await self._chk_wdog_pet()
        await self._chk_reference_counter()
        await self._chk_regwen_lock_and_nonvac()
        # Each facet logs its own PASS line, and the plan rows key on those.

    async def _read_refcnt(self) -> int:
        """The 64-bit reference count, high half first.

        Reading high then low, and requiring the high half to be unchanged
        afterwards, is what keeps a carry between the two reads from being
        reported as a count that went backwards.
        """
        hi = await self.wdt.read(REFERENCE_COUNTER_HI)
        lo = await self.wdt.read(REFERENCE_COUNTER_LO)
        hi_again = await self.wdt.read(REFERENCE_COUNTER_HI)
        if hi_again != hi:
            # A carry landed between the halves; take the pair again on the
            # new high half rather than returning a torn value.
            lo = await self.wdt.read(REFERENCE_COUNTER_LO)
            hi = hi_again
        return (hi << 32) | lo

    async def _chk_reference_counter(self) -> None:
        """CHK-REFCNT-RUNS on SEP_CPU_CTRL.REFERENCE_COUNTER.

        The counter is the one piece of SEP that runs on clk_ref_i rather than
        clk_i: prim_refclk_count_w_cdc counts on the reference edge and
        resynchronises the value across to clk_i for the CSR read. Both halves
        of that crossing are dark whenever the reference clock is not driven,
        and a frozen counter reads as a perfectly stable CSR.
        """
        first = await self._read_refcnt()
        await ClockCycles(cocotb.top.clk_i, 400)
        second = await self._read_refcnt()
        await self._grade(
            second > first,
            "CHK-REFCNT-RUNS",
            f"REFERENCE_COUNTER did not advance across a "
            f"400-cycle window ({first} -> {second}). The counter runs on "
            "clk_ref_i and resynchronises onto clk_i; a reference clock that is "
            "not running, or a CDC that never hands the value over, both read as "
            "a stable count",
        )
        self.logger.info(
            "CHK-REFCNT-RUNS PASS: REFERENCE_COUNTER %d -> %d across 400 core "
            "cycles, so the clk_ref_i counter and its crossing onto clk_i are live",
            first,
            second,
        )

        # A software load of REFERENCE_COUNTER is not graded. The update crosses a
        # depth-1 async FIFO that drops an update arriving before the previous one
        # has crossed, with no error indication, and CntUpdateAccepted_A is compiled
        # out by COMMON_CELLS_ASSERTS_OFF; with clk_i at 1.25 ns and clk_ref_i at
        # 10 ns the loss is silent.

    async def _timed_read(self, addr: int) -> tuple[int, int, int]:
        """Read ``addr``; return the value and the simulation times (ps) of issue and response."""
        t_issue = int(get_sim_time("ps"))
        val = await self.wdt.read(addr)
        return val, t_issue, int(get_sim_time("ps"))

    async def _settled_count(self, chk: str, count_reg: int) -> tuple[int, int]:
        """Read a stopped counter until two reads ``_SETTLE_TICKS`` apart agree.

        Return the first read and the settled value. The age of a count read is
        not stated (``OBS-WDT-COUNT-AGE``), so the first read after the stop can
        still show an older count; a stopped counter does not change, so equal
        reads give its value.
        """
        clk = cocotb.top.clk_wdt_i
        first = await self.wdt.read(count_reg)
        prev = first
        for _ in range(_SETTLE_POLLS):
            await ClockCycles(clk, _SETTLE_TICKS)
            cur = await self.wdt.read(count_reg)
            if cur == prev:
                return first, cur
            prev = cur
        await self._grade(
            False,
            chk,
            f"precondition: the stopped count at 0x{count_reg:x} did not settle in "
            f"{_SETTLE_POLLS} reads {_SETTLE_TICKS} ticks apart (first {first}, last {prev})",
        )
        return first, prev

    async def _stopped_run(
        self, chk: str, ctrl: int, enable: int, count_reg: int, ticks: int
    ) -> dict[str, int]:
        """Run a counter for exactly ``ticks`` clk_wdt edges between two control writes.

        The counter is stopped on entry, its count preset by the caller. The enable write
        and the stop write (0) to ``ctrl`` are issued at a rising clk_wdt edge,
        ``ticks`` edges apart. Each control write is read back before the next
        step: a read back "will guarantee the completion of all previous
        writes" (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/doc/theory_of_operation.md:26-28``).
        A timer counts only while its enable is set (``theory_of_operation.md:4``),
        so after the stop write the count is fixed and ``_settled_count`` reads
        it. The return holds that count, the first read after the stop, and the
        write response times in ps.
        """
        clk = cocotb.top.clk_wdt_i
        period = round(self.cfg.wdt_clk_period_ns * 1000)
        await RisingEdge(clk)
        t_on = int(get_sim_time("ps"))
        await self.wdt.write(ctrl, enable)
        on_resp = int(get_sim_time("ps")) - t_on
        rb_on = await self.wdt.read(ctrl)
        t_off = t_on + ticks * period
        now = int(get_sim_time("ps"))
        await self._grade(
            rb_on == enable and now <= t_off - period,
            chk,
            f"precondition: enable readback 0x{rb_on:x} expected 0x{enable:x}, done at "
            f"{now} ps, stop write due at {t_off} ps",
        )
        await Timer(t_off - now - period // 2, units="ps")
        await RisingEdge(clk)
        t_stop = int(get_sim_time("ps"))
        await self.wdt.write(ctrl, 0)
        off_resp = int(get_sim_time("ps")) - t_stop
        rb_off = await self.wdt.read(ctrl)
        await self._grade(
            rb_off == 0 and t_stop == t_off,
            chk,
            f"precondition: stop readback 0x{rb_off:x} expected 0x0, stop write at "
            f"{t_stop} ps expected {t_off} ps",
        )
        first, count = await self._settled_count(chk, count_reg)
        return {
            "count": count,
            "first": first,
            "on_resp": on_resp,
            "off_resp": off_resp,
        }

    async def _run_pair(
        self, chk: str, ctrl: int, enable: int, count_regs: tuple[int, ...], ticks: int, d: int
    ) -> tuple[int, int, str]:
        """Count advance between two stopped runs of ``_RUN_BASE_TICKS`` and ``_RUN_BASE_TICKS + ticks``.

        Each run starts from a stopped counter at 0 (written and read back).
        Both runs have the same control writes at the same clk_wdt phase, so
        the clk_wdt edges from a control write to its effect on the count are
        the same in both runs (the write responses must take the same time).
        That latency is not stated, and the difference of the two stopped
        counts cancels it: with ``ticks`` a multiple of the divisor ``d`` and
        the prescaler count reset by each control write, the difference is
        ``ticks / d`` exactly. Return the advance, ``ticks / d`` and a log
        fragment with both runs.
        """
        runs = []
        for w in (_RUN_BASE_TICKS, _RUN_BASE_TICKS + ticks):
            await self.wdt.write(ctrl, 0)
            rb = await self.wdt.read(ctrl)
            for reg in count_regs:
                await self.wdt.write(reg, 0)
            zero = [await self.wdt.read(reg) for reg in count_regs]
            await self._grade(
                rb == 0 and not any(zero),
                chk,
                f"precondition: stopped counter readback ctrl=0x{rb:x} count={zero}, "
                f"expected 0 and 0",
            )
            runs.append(await self._stopped_run(chk, ctrl, enable, count_regs[-1], w))
        ra, rb_ = runs
        await self._grade(
            ra["on_resp"] == rb_["on_resp"] and ra["off_resp"] == rb_["off_resp"],
            chk,
            f"precondition: control write responses differ between the runs "
            f"(enable {ra['on_resp']}/{rb_['on_resp']} ps, stop {ra['off_resp']}/"
            f"{rb_['off_resp']} ps)",
        )
        adv = (rb_["count"] - ra["count"]) & 0xFFFF_FFFF
        frag = (
            f"runs {_RUN_BASE_TICKS}/{_RUN_BASE_TICKS + ticks} ticks stopped at "
            f"{ra['count']}/{rb_['count']}"
        )
        for tag, w, r in (("a", _RUN_BASE_TICKS, ra), ("b", _RUN_BASE_TICKS + ticks, rb_)):
            self.logger.info(
                "OBS-WDT-COUNT-AGE: %s run=%s ctrl=0x%x ticks=%d d=%d stopped=%d "
                "first_read_after_stop=%d offset=%d",
                chk,
                tag,
                ctrl,
                w,
                d,
                r["count"],
                r["first"],
                r["count"] - w // d,
            )
        return adv, ticks // d, frag

    async def _wkup_pair(
        self, chk: str, prescaler: int, ticks: int, d: int
    ) -> tuple[int, int, str]:
        """``_run_pair`` on the wakeup counter with ``prescaler``; the threshold stays high."""
        await self.wdt.write(WKUP_THOLD_HI, 0)
        await self.wdt.write(WKUP_THOLD_LO, self.cfg_wdt.wkup_high_thold)
        return await self._run_pair(
            chk,
            WKUP_CTRL,
            WKUP_ENABLE | (prescaler << WKUP_PRESCALER_SHIFT),
            (WKUP_COUNT_HI, WKUP_COUNT_LO),
            ticks,
            d,
        )

    async def _chk_wkup_count(self) -> None:
        """CHK-WKUP-COUNT: with prescaler 0 WKUP_COUNT advances by one per clk_wdt tick.

        The rate is "one more than the 12-bit WKUP_CTRL.prescaler field" cycles
        per count (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:32``),
        so at prescaler 0 two stopped runs ``_COUNT_WINDOW_TICKS`` edges apart in
        length differ by exactly ``_COUNT_WINDOW_TICKS`` counts (``_run_pair``).
        ``INTR_STATE.wkup_expired`` stays 0 under the high threshold of both runs.
        """
        adv, exp, frag = await self._wkup_pair(
            "CHK-WKUP-COUNT", 0, _COUNT_WINDOW_TICKS, aon_timer_wkup_ticks_per_count(0)
        )
        await self._grade(
            adv == exp,
            "CHK-WKUP-COUNT",
            f"WKUP_COUNT advanced {adv} with prescaler 0 over {_COUNT_WINDOW_TICKS} more "
            f"ticks, expected {exp} ({frag})",
        )
        intr = await self.wdt.read(INTR_STATE)
        exp_quiet = 0
        await self._grade(
            (intr & INTR_WKUP_EXPIRED) == exp_quiet,
            "CHK-WKUP-COUNT",
            f"high threshold expired in the count runs: wkup_expired="
            f"0x{intr & INTR_WKUP_EXPIRED:x} expected 0x{exp_quiet:x} "
            f"(INTR_STATE=0x{intr:08x}, advance={adv}, thold={self.cfg_wdt.wkup_high_thold})",
        )
        # A write of INTR_TEST.wkup_timer_expired forces the status bit.
        await self.wdt.write(INTR_TEST, INTR_TEST_WKUP_EXPIRED)
        forced = await self.wdt.read(INTR_STATE)
        exp_forced = INTR_WKUP_EXPIRED
        await self._grade(
            (forced & INTR_WKUP_EXPIRED) == exp_forced,
            "CHK-WKUP-COUNT",
            f"INTR_TEST did not force INTR_STATE.wkup_expired: "
            f"0x{forced & INTR_WKUP_EXPIRED:x} expected 0x{exp_forced:x} (0x{forced:08x})",
        )
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)
        self.logger.info(
            "CHK-WKUP-COUNT PASS: WKUP_COUNT advanced %d with prescaler 0 over %d more "
            "ticks, expected %d (%s); wkup_expired under the high threshold=0x%x expected "
            "0x%x; intr_test_forced=0x%x expected 0x%x (INTR_STATE=0x%08x)",
            adv,
            _COUNT_WINDOW_TICKS,
            exp,
            frag,
            intr & INTR_WKUP_EXPIRED,
            exp_quiet,
            forced & INTR_WKUP_EXPIRED,
            exp_forced,
            forced,
        )

    async def _chk_wkup_prescale(self) -> None:
        """CHK-WKUP-PRESCALE: WKUP_CTRL.prescaler divides the wakeup count rate by prescaler + 1.

        "The number of cycles per tick is one more than the 12-bit
        WKUP_CTRL.prescaler field"
        (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:32``), and
        each WKUP_CTRL write resets the internal prescaler count
        (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/doc/registers.md:42``),
        so every stopped run starts its prescaler count at the enable write. The
        rate is carried by ``sep_spec_tables.aon_timer_wkup_ticks_per_count``.
        Two stopped runs whose lengths differ by W = _PRESCALE_STEPS_PER_P x P x D
        ticks, D = prescaler + 1, differ by exactly W / D counts (``_run_pair``);
        the undivided pair differs by exactly W. A divisor of P gives 3 x (P + 1)
        counts and a divisor of 2 x D gives 1.5 x P counts, so both fail.
        """
        presc = self.cfg_wdt.wkup_prescaler
        div = aon_timer_wkup_ticks_per_count(presc)
        window = _PRESCALE_STEPS_PER_P * presc * div
        adv_fast, exp_fast, frag_fast = await self._wkup_pair(
            "CHK-WKUP-PRESCALE", 0, window, aon_timer_wkup_ticks_per_count(0)
        )
        await self._grade(
            adv_fast == exp_fast,
            "CHK-WKUP-PRESCALE",
            f"prescaler=0 advanced {adv_fast} over {window} more ticks, expected {exp_fast} "
            f"({frag_fast})",
        )
        adv_slow, exp_slow, frag_slow = await self._wkup_pair(
            "CHK-WKUP-PRESCALE", presc, window, div
        )
        await self._grade(
            adv_slow == exp_slow,
            "CHK-WKUP-PRESCALE",
            f"prescaler={presc} advanced {adv_slow} over {window} more ticks, expected "
            f"{exp_slow} at {div} ticks per count ({frag_slow})",
        )
        self.logger.info(
            "CHK-WKUP-PRESCALE PASS: over %d more ticks WKUP_COUNT advanced %d with "
            "prescaler=0 (expected %d; %s) and %d with prescaler=%d (expected %d at %d "
            "ticks per count; %s)",
            window,
            adv_fast,
            exp_fast,
            frag_fast,
            adv_slow,
            presc,
            exp_slow,
            div,
            frag_slow,
        )

    async def _expiry_quiet(self, chk: str, thold: int, count: int) -> tuple[int, int]:
        """Stop the wakeup counter, preset its count and threshold, and clear both expiry flags.

        The writes are followed by readbacks (a read back "will guarantee the
        completion of all previous writes",
        ``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/doc/theory_of_operation.md:26-28``).
        As a precondition on the ``chk`` line, the readbacks equal the written
        values and ``INTR_STATE.wkup_expired`` and ``WKUP_CAUSE.cause`` read 0
        before the counter is enabled, so a set read later comes from the run
        that follows. Return the INTR_STATE and WKUP_CAUSE reads.
        """
        await self.wdt.write(WKUP_CTRL, 0)
        await self.wdt.write(WKUP_COUNT_HI, 0)
        await self.wdt.write(WKUP_COUNT_LO, count)
        await self.wdt.write(WKUP_THOLD_HI, 0)
        await self.wdt.write(WKUP_THOLD_LO, thold)
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)
        await self.wdt.write(WKUP_CAUSE, 0)
        exp_rb = [0, 0, count, 0, thold]
        rb = [
            await self.wdt.read(reg)
            for reg in (WKUP_CTRL, WKUP_COUNT_HI, WKUP_COUNT_LO, WKUP_THOLD_HI, WKUP_THOLD_LO)
        ]
        intr = await self.wdt.read(INTR_STATE)
        cause = await self.wdt.read(WKUP_CAUSE)
        await self._grade(
            rb == exp_rb and (intr & INTR_WKUP_EXPIRED) == 0 and (cause & WKUP_CAUSE_BIT) == 0,
            chk,
            f"precondition: before the enable WKUP_CTRL/COUNT_HI/COUNT_LO/THOLD_HI/THOLD_LO "
            f"read {[hex(v) for v in rb]} expected {[hex(v) for v in exp_rb]}, "
            f"wkup_expired=0x{intr & INTR_WKUP_EXPIRED:x} cause=0x{cause & WKUP_CAUSE_BIT:x} "
            f"expected 0x0 and 0x0",
        )
        return intr, cause

    async def _chk_wkup_expire(self) -> None:
        """CHK-WKUP-EXPIRE (set): wkup_expired sets with the count at or above WKUP_THOLD.

        The expiry fires "each time the pre-scaler completes when the count is
        at or above the threshold"
        (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:35``).
        With the counter stopped, the count 0 and both flags read 0
        (``_expiry_quiet``), the counter is enabled with prescaler 0 and
        ``INTR_STATE`` is polled until ``wkup_expired`` sets (bounded; the bound
        FAILs). The counter is then stopped and its count is read until it
        settles (``_settled_count``). A count read while the counter runs is a
        copy of unstated age (``OBS-WDT-COUNT-AGE``: the first read after a stop
        can be several counts behind the stopped count), so a running count
        read is not graded against the threshold. The settled stopped count is
        the count at the stop, which follows the observed set, and the counter
        only counts up from 0 here (``WKUP_COUNT_HI`` reads 0, no wrap), so it
        is at or above the count at the set and must be at or above
        ``WKUP_THOLD``. An expiry that fires further below the threshold than
        the counts between the set and the stop fails here; the point at the
        threshold is graded by ``_chk_wkup_expire_point``.
        """
        chk = "CHK-WKUP-EXPIRE"
        thold = self.cfg_wdt.wkup_thold
        intr_pre, cause_pre = await self._expiry_quiet(chk, thold, 0)
        await self.wdt.write(WKUP_CTRL, WKUP_ENABLE)
        ok, val = await self._poll_bit_set(
            INTR_STATE, INTR_WKUP_LSB, timeout_cycles=300 * self._tick, step=4 * self._tick
        )
        await self._grade(
            ok,
            chk,
            f"WKUP_COUNT>=THOLD never set INTR_STATE.wkup_expired (INTR_STATE=0x{val:08x})",
        )
        await self.wdt.write(WKUP_CTRL, 0)  # stop the counter
        rb_off = await self.wdt.read(WKUP_CTRL)
        await self._grade(
            rb_off == 0,
            chk,
            f"precondition: WKUP_CTRL readback after the stop 0x{rb_off:x} expected 0x0",
        )
        _, stopped = await self._settled_count(chk, WKUP_COUNT_LO)
        stopped_hi = await self.wdt.read(WKUP_COUNT_HI)
        floor = thold
        await self._grade(
            stopped_hi == 0 and stopped >= floor,
            chk,
            f"wkup_expired set with the stopped count HI=0x{stopped_hi:x} LO={stopped}, "
            f"expected HI=0 and LO>={floor} (WKUP_THOLD; INTR_STATE=0x{val:08x})",
        )
        self.logger.info(
            "CHK-WKUP-EXPIRE PASS (set): before the enable wkup_expired=0x%x expected 0x0; "
            "set read wkup_expired=1 (0x%08x); stopped count after the set HI=0x%x LO=%d, "
            "expected HI=0 and LO>=%d (WKUP_THOLD)",
            intr_pre & INTR_WKUP_EXPIRED,
            val,
            stopped_hi,
            stopped,
            floor,
        )

        # CHK-WKUP-CAUSE: WKUP_CAUSE.cause is the wakeup request (registers.md:260),
        # raised on the same expiry as INTR_STATE.wkup_expired (README.md:35-36) and
        # held until software writes 0 (README.md:41). It read 0 before the enable
        # (_expiry_quiet) and must read 1 here, with the stopped count graded at or
        # above the threshold above. To clear it the count is first reset below the
        # threshold, then 0 is written.
        cause = await self.wdt.read(WKUP_CAUSE)
        exp_set = WKUP_CAUSE_BIT
        await self._grade(
            (cause & WKUP_CAUSE_BIT) == exp_set,
            "CHK-WKUP-CAUSE",
            f"WKUP_CAUSE.cause not set after wkup expiry: cause_pre=0x"
            f"{cause_pre & WKUP_CAUSE_BIT:x} cause_set=0x{cause & WKUP_CAUSE_BIT:x} "
            f"expected 0x{exp_set:x} (0x{cause:08x}; stopped count {stopped}, WKUP_THOLD {thold})",
        )
        await self.wdt.write(WKUP_COUNT_HI, 0)  # remove the wakeup condition
        await self.wdt.write(WKUP_COUNT_LO, 0)
        # The COUNT writes are AON-domain too. Read COUNT back below the threshold
        # first, so the cause read below samples the AON state after the condition
        # is gone, not before the write crossed.
        clear_budget = 100 * self._tick
        low, cnt_lo = await self._poll_at_most(
            WKUP_COUNT_LO,
            self.cfg_wdt.wkup_thold - 1,
            timeout_cycles=clear_budget,
            step=4 * self._tick,
        )
        cnt_hi = await self.wdt.read(WKUP_COUNT_HI)
        await self._grade(
            low and cnt_hi == 0,
            "CHK-WKUP-CAUSE",
            f"WKUP_COUNT did not read back below WKUP_THOLD={self.cfg_wdt.wkup_thold} "
            f"after the reset write: count_after_reset HI=0x{cnt_hi:08x} LO=0x{cnt_lo:08x}, "
            f"expected HI=0 and LO<=0x{self.cfg_wdt.wkup_thold - 1:x}",
        )
        # Hold for the same budget the write-0 clear below is given. A level-only
        # cause would drop within it, as the write-0 clear must.
        await ClockCycles(cocotb.top.clk_i, clear_budget)
        # Sticky: dropping the count must leave the cause set, otherwise the write-0
        # below cannot be blamed for the clear.
        cause_held = await self.wdt.read(WKUP_CAUSE)
        exp_held = WKUP_CAUSE_BIT
        await self._grade(
            (cause_held & WKUP_CAUSE_BIT) == exp_held,
            "CHK-WKUP-CAUSE",
            f"WKUP_CAUSE.cause after the COUNT reset: cause_held=0x{cause_held & WKUP_CAUSE_BIT:x} "
            f"expected 0x{exp_held:x} (0x{cause_held:08x}); a cleared cause leaves the "
            f"write-0 clear unattributed",
        )
        # OpenTitan aon_timer WKUP_CAUSE: SW writes 0 to acknowledge/clear the cause.
        await self.wdt.write(WKUP_CAUSE, 0)
        # WKUP_CAUSE is AON-domain (clk_aon=clk_wdt): the clear settles over a few clk_wdt
        # cycles via the register CDC, so poll rather than read back immediately.
        ccleared, cpost = await self._poll_bit_clear(
            WKUP_CAUSE, WKUP_CAUSE_LSB, timeout_cycles=clear_budget, step=4 * self._tick
        )
        await self._grade(
            ccleared,
            "CHK-WKUP-CAUSE",
            f"WKUP_CAUSE.cause not cleared after condition removal + write 0 (0x{cpost:08x})",
        )
        self.logger.info(
            "CHK-WKUP-CAUSE PASS: cause_pre=0x%x expected 0x0; cause_set=0x%x expected 0x%x; "
            "count_after_reset HI=0x%08x LO=0x%08x expected HI=0 and LO<=0x%x; cause_held=0x%x "
            "expected 0x%x; cause_after_write0=0x%x expected 0 (0x%08x)",
            cause_pre & WKUP_CAUSE_BIT,
            cause & WKUP_CAUSE_BIT,
            exp_set,
            cnt_hi,
            cnt_lo,
            self.cfg_wdt.wkup_thold - 1,
            cause_held & WKUP_CAUSE_BIT,
            exp_held,
            cpost & WKUP_CAUSE_BIT,
            cpost,
        )

        # CHK-WKUP-EXPIRE (RW1C): INTR_STATE.wkup_expired is an edge-latched sticky -> W1C clears
        # it (the counter is already reset/disabled, so it cannot re-set). The counter stop,
        # the COUNT reset and the WKUP_CAUSE clear above must leave it set, so it is read
        # as 1 right before the W1C; the W1C is then the only step that can clear it.
        pre_w1c = await self.wdt.read(INTR_STATE)
        exp_pre_w1c = INTR_WKUP_EXPIRED
        await self._grade(
            (pre_w1c & INTR_WKUP_EXPIRED) == exp_pre_w1c,
            "CHK-WKUP-EXPIRE",
            f"precondition (RW1C): wkup_expired before the W1C=0x{pre_w1c & INTR_WKUP_EXPIRED:x} "
            f"expected 0x{exp_pre_w1c:x} (INTR_STATE=0x{pre_w1c:08x}); the counter stop, the "
            f"COUNT reset or the WKUP_CAUSE clear dropped it",
        )
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)  # W1C
        post = await self.wdt.read(INTR_STATE)
        await self._grade(
            (post & INTR_WKUP_EXPIRED) == 0,
            "CHK-WKUP-EXPIRE",
            f"INTR_STATE.wkup_expired not cleared by W1C (0x{post:08x})",
        )
        self.logger.info(
            "CHK-WKUP-EXPIRE PASS (RW1C): before the W1C wkup_expired=0x%x expected 0x%x "
            "(0x%08x); W1C cleared wkup_expired -> 0 (0x%08x)",
            pre_w1c & INTR_WKUP_EXPIRED,
            exp_pre_w1c,
            pre_w1c,
            post,
        )

    async def _expire_leg(self, leg: str, thold: int, start: int) -> dict[str, int]:
        """One stopped run of ``_RUN_BASE_TICKS`` from ``start`` under ``thold``; return the reads.

        ``_expiry_quiet`` presets the count and threshold and proves both flags
        0 before the enable. After the stopped run (``_stopped_run``) the
        counter waits ``_EXPIRE_WAIT_TICKS`` clk_wdt ticks, then
        ``INTR_STATE`` and ``WKUP_CAUSE`` are read once.
        """
        chk = "CHK-WKUP-EXPIRE"
        await self._expiry_quiet(chk, thold, start)
        run = await self._stopped_run(chk, WKUP_CTRL, WKUP_ENABLE, WKUP_COUNT_LO, _RUN_BASE_TICKS)
        hi = await self.wdt.read(WKUP_COUNT_HI)
        await ClockCycles(cocotb.top.clk_wdt_i, _EXPIRE_WAIT_TICKS)
        intr = await self.wdt.read(INTR_STATE)
        cause = await self.wdt.read(WKUP_CAUSE)
        self.logger.info(
            "OBS-WDT-COUNT-AGE: %s leg=%s ticks=%d start=%d stopped=%d first_read_after_stop=%d",
            chk,
            leg,
            _RUN_BASE_TICKS,
            start,
            run["count"],
            run["first"],
        )
        return {"count": run["count"], "hi": hi, "intr": intr, "cause": cause}

    async def _wkup_count_at_set(self, out: dict) -> None:
        """Record wkup_count on the first clk_wdt_i edge where the wakeup interrupt reads 1."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_wdt_i)
            await ReadOnly()
            v = self.rd(dut.aon_wkup_probe_o, allow_unknown=True)
            if v >> 32 & 1:
                out["count"] = v & 0xFFFF_FFFF
                return

    async def _chk_wkup_expire_point(self) -> None:
        """CHK-WKUP-EXPIRE (point) and CHK-WKUP-CAUSE (point): the expiry fires at the threshold.

        The expiry fires "each time the pre-scaler completes when the count is
        at or above the threshold"
        (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:35``),
        and it raises both ``INTR_STATE.wkup_expired`` and the wakeup request
        ``WKUP_CAUSE.cause`` (README.md:35-36, ``doc/registers.md:260``). A
        timer counts only while enabled (``doc/theory_of_operation.md:4``), so
        with prescaler 0 every completion of a stopped run from ``start`` to
        the stopped count C compares a count in ``start`` .. C (the text does
        not say whether the compare sees the count before or after the
        increment of that completion, so both are allowed). The stopped count
        C is exact: it is read until it settles, so the unstated age of a count
        read and the unstated write-to-count latency do not enter the grade.
        Two stopped runs under one threshold T = ``wkup_thold`` +
        ``_RUN_BASE_TICKS``:

        * below: the run starts ``_EXPIRE_GUARD`` + 1 counts under the start
          that would end on T, so C < T is expected; with C < T every compared
          count is below T and both flags must stay 0. The run must advance
          (C > start), so the counter was live.
        * above: the run starts ``_EXPIRE_GUARD`` + 1 counts over that start,
          so C > T is expected; with C >= T + 1 the last completion compared
          C - 1 or C, both at or above T, and both flags must be 1.

        C < T and C > T are preconditions on the check line (the guard leaves
        room for an unstated latency in the run length). Each flag is read once,
        ``_EXPIRE_WAIT_TICKS`` clk_wdt ticks after the stopped count settles: the
        above leg must show the set within that bound, and the below leg is
        read after the same bound. An expiry earlier than the count C of the
        below leg or later than the count C - 1 of the above leg fails. The
        stopped counts are logged as ``OBS-WDT-COUNT-AGE``.
        """
        chk = "CHK-WKUP-EXPIRE"
        thold = self.cfg_wdt.wkup_thold + _RUN_BASE_TICKS
        on_t = thold - _RUN_BASE_TICKS  # the start whose run would end on T
        start_b = on_t - 1 - _EXPIRE_GUARD
        below = await self._expire_leg("below", thold, start_b)
        await self._grade(
            below["hi"] == 0 and start_b < below["count"] < thold,
            chk,
            f"precondition: below leg stopped count HI=0x{below['hi']:x} LO={below['count']}, "
            f"expected HI=0 and {start_b} < LO < {thold} (WKUP_THOLD)",
        )
        exp_below = 0
        b_intr = below["intr"] & INTR_WKUP_EXPIRED
        b_cause = below["cause"] & WKUP_CAUSE_BIT
        await self._grade(
            b_intr == exp_below,
            chk,
            f"below leg: stopped count {below['count']} < WKUP_THOLD {thold}, "
            f"wkup_expired=0x{b_intr:x} expected 0x{exp_below:x} (INTR_STATE=0x{below['intr']:08x})",
        )
        await self._grade(
            b_cause == 0,
            "CHK-WKUP-CAUSE",
            f"below leg: stopped count {below['count']} < WKUP_THOLD {thold}, "
            f"cause=0x{b_cause:x} expected 0x0 (WKUP_CAUSE=0x{below['cause']:08x})",
        )
        start_a = on_t + 1 + _EXPIRE_GUARD
        tap: dict = {}
        sampler = cocotb.start_soon(self._wkup_count_at_set(tap))
        above = await self._expire_leg("above", thold, start_a)
        sampler.cancel()
        # No line states which count the core compares at the completion that
        # sets the expiry: the count on the wakeup tap at that edge is logged.
        self.logger.info(
            "OBS-WKUP-EXPIRE-COUNT thold=%d count_at_set=%s",
            thold,
            tap.get("count", "none"),
        )
        await self._grade(
            above["hi"] == 0 and above["count"] > thold and start_a < thold,
            chk,
            f"precondition: above leg from {start_a} stopped count HI=0x{above['hi']:x} "
            f"LO={above['count']}, expected HI=0 and LO > {thold} (WKUP_THOLD)",
        )
        exp_above = 1
        a_intr = above["intr"] & INTR_WKUP_EXPIRED
        a_cause = above["cause"] & WKUP_CAUSE_BIT
        await self._grade(
            a_intr == exp_above,
            chk,
            f"above leg: stopped count {above['count']} > WKUP_THOLD {thold}, "
            f"wkup_expired=0x{a_intr:x} expected 0x{exp_above:x} (INTR_STATE=0x{above['intr']:08x})",
        )
        await self._grade(
            a_cause == WKUP_CAUSE_BIT,
            "CHK-WKUP-CAUSE",
            f"above leg: stopped count {above['count']} > WKUP_THOLD {thold}, "
            f"cause=0x{a_cause:x} expected 0x{WKUP_CAUSE_BIT:x} (WKUP_CAUSE=0x{above['cause']:08x})",
        )
        self.logger.info(
            "CHK-WKUP-EXPIRE PASS (point): WKUP_THOLD=%d; below leg %d -> %d wkup_expired=0x%x "
            "expected 0x0; above leg %d -> %d wkup_expired=0x%x expected 0x1",
            thold,
            start_b,
            below["count"],
            b_intr,
            start_a,
            above["count"],
            a_intr,
        )
        self.logger.info(
            "CHK-WKUP-CAUSE PASS (point): WKUP_THOLD=%d; below leg stopped at %d cause=0x%x "
            "expected 0x0; above leg stopped at %d cause=0x%x expected 0x1",
            thold,
            below["count"],
            b_cause,
            above["count"],
            a_cause,
        )
        # Leave the wakeup timer stopped at count 0 with both flags clear.
        await self._expiry_quiet(chk, thold, 0)

    async def _chk_intr_test(self) -> None:
        """CHK-INTR-TEST: INTR_TEST.wkup_timer_expired forces INTR_STATE.wkup_expired.

        The wakeup counter is disabled and zeroed first, so nothing but the INTR_TEST
        write can raise the status bit (aon_timer.sv drives prim_intr_hw from
        reg2hw.intr_test). W1C then clears it again.
        """
        await self.wdt.write(WKUP_CTRL, 0)  # counter off: the set below is attributable
        await self.wdt.write(WKUP_COUNT_HI, 0)
        await self.wdt.write(WKUP_COUNT_LO, 0)
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)  # clear any stale status
        pre = await self.wdt.read(INTR_STATE)
        await self._grade(
            (pre & INTR_WKUP_EXPIRED) == 0,
            "CHK-INTR-TEST",
            f"INTR_STATE.wkup_expired already set before the force "
            f"(0x{pre:08x}); the set below would be unattributed",
        )
        await self.wdt.write(INTR_TEST, INTR_TEST_WKUP_EXPIRED)
        ok, val = await self._poll_bit_set(
            INTR_STATE, INTR_WKUP_LSB, timeout_cycles=100 * self._tick, step=4 * self._tick
        )
        await self._grade(
            ok,
            "CHK-INTR-TEST",
            f"INTR_TEST did not set wkup_expired (INTR_STATE=0x{val:08x})",
        )
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)  # W1C
        post = await self.wdt.read(INTR_STATE)
        await self._grade(
            (post & INTR_WKUP_EXPIRED) == 0,
            "CHK-INTR-TEST",
            f"W1C did not clear the forced wkup_expired (0x{post:08x})",
        )
        self.logger.info(
            "CHK-INTR-TEST PASS: INTR_TEST forced INTR_STATE.wkup_expired (0x%08x) with the "
            "wakeup counter off, and W1C cleared it (0x%08x)",
            val,
            post,
        )

    async def _chk_wdog_pet(self) -> None:
        """CHK-WDOG-PET: WDOG_COUNT advances by one per clk_wdt tick, and a write of 0 (pet) resets it.

        "Once the timer is enabled, it increments on every tick of the AON
        clock" (``vendor/lowRISC/opentitan/upstream/hw/ip/aon_timer/README.md:52``),
        and petting is "resetting the count to zero" (README.md:58). Two stopped
        watchdog runs whose lengths differ by ``_PET_WINDOW_TICKS`` ticks differ
        by exactly that many counts (``_run_pair``). The watchdog then runs
        again from the stopped count of the longer run and is petted. The pet
        write lands in the AON domain after its issue and before the read that
        follows completes (a read back "will guarantee the completion of all
        previous writes", ``doc/theory_of_operation.md:26-28``), so the count
        that read returns is at most the clk_wdt edges from the issue of the pet
        to the response of the read, and that bound is below the stopped count.
        """
        # REGWEN is 1 at reset (unlocked); set high thresholds so no bark/bite fires.
        await self.wdt.write(WDOG_BARK_THOLD, 0x00FF_FFFF)
        await self.wdt.write(WDOG_BITE_THOLD, 0x00FF_FFFF)
        adv, exp, frag = await self._run_pair(
            "CHK-WDOG-PET", WDOG_CTRL, WDOG_ENABLE, (WDOG_COUNT,), _PET_WINDOW_TICKS, 1
        )
        await self._grade(
            adv == exp,
            "CHK-WDOG-PET",
            f"WDOG_COUNT advanced {adv} over {_PET_WINDOW_TICKS} more ticks, expected "
            f"{exp} ({frag})",
        )
        count1 = await self.wdt.read(WDOG_COUNT)  # the stopped count of the longer run
        await self.wdt.write(WDOG_CTRL, WDOG_ENABLE)
        rb_on = await self.wdt.read(WDOG_CTRL)
        await self._grade(
            rb_on == WDOG_ENABLE,
            "CHK-WDOG-PET",
            f"precondition: WDOG_CTRL readback 0x{rb_on:x} expected 0x{WDOG_ENABLE:x}",
        )
        await ClockCycles(cocotb.top.clk_wdt_i, _RUN_BASE_TICKS)
        period = round(self.cfg.wdt_clk_period_ns * 1000)
        t_pet = int(get_sim_time("ps"))
        await self.wdt.write(WDOG_COUNT, 0)  # pet
        count2, _, t_rd = await self._timed_read(WDOG_COUNT)
        pet_hi = -(-(t_rd - t_pet) // period)
        await self._grade(
            count2 <= pet_hi and pet_hi < count1,
            "CHK-WDOG-PET",
            f"WDOG_COUNT after the pet is {count2}, expected 0..{pet_hi} (clk_wdt edges "
            f"from the pet issue to the read response); pre-pet count at least {count1}",
        )
        self.logger.info(
            "CHK-WDOG-PET PASS: WDOG_COUNT advanced %d over %d more ticks, expected %d "
            "(%s); after the pet it reads %d, expected 0..%d",
            adv,
            _PET_WINDOW_TICKS,
            exp,
            frag,
            count2,
            pet_hi,
        )

    async def _chk_regwen_lock_and_nonvac(self) -> None:
        """CHK-NONVAC + CHK-REGWEN-LOCK on WDOG_BARK_THOLD and WDOG_BITE_THOLD.

        Spec: aon_timer.hjson:247 "Once cleared, the watchdog configuration will
        be locked until the next reset.", with ``regwen: "WDOG_REGWEN"`` on
        WDOG_BARK_THOLD (:274) and WDOG_BITE_THOLD (:287).

        CHK-NONVAC: with WDOG_REGWEN still 1, a write of a value other than the
        register's current value lands on each threshold, so the same write path
        is live. CHK-REGWEN-LOCK: after WDOG_REGWEN is written 0 and reads 0, a
        write of another value to each threshold is ignored: the readback is the
        whole pre-lock value. The graded window of this leaf opens only around
        the two locked writes and their readbacks; the readback compare of each
        threshold is the compare of its ``cp_lock_scope`` bin.
        """
        chk_nv = "CHK-NONVAC"
        bark_pre = self.cfg_wdt.bark_prelock
        bite_pre = self.lock_draws.bite_prelock
        bark_entry = await self.wdt.read(WDOG_BARK_THOLD)
        bite_entry = await self.wdt.read(WDOG_BITE_THOLD)
        await self._grade(
            bark_pre != (bark_entry & _BARK_MASK) and bite_pre != (bite_entry & _BITE_MASK),
            chk_nv,
            f"CTRL-MISSING pre-lock values equal the entry values (bark 0x{bark_entry:08x} "
            f"vs 0x{bark_pre:08x}, bite 0x{bite_entry:08x} vs 0x{bite_pre:08x}); a write "
            f"that does not land would still read back",
        )
        await self.wdt.write(WDOG_BARK_THOLD, bark_pre)
        bark_rb = await self.wdt.read(WDOG_BARK_THOLD)
        await self._grade(
            bark_rb == bark_pre,
            chk_nv,
            f"reg=WDOG_BARK_THOLD pre-lock write did not land: entry=0x{bark_entry:08x} "
            f"wrote=0x{bark_pre:08x} read=0x{bark_rb:08x}",
        )
        await self.wdt.write(WDOG_BITE_THOLD, bite_pre)
        bite_rb = await self.wdt.read(WDOG_BITE_THOLD)
        await self._grade(
            bite_rb == bite_pre,
            chk_nv,
            f"reg=WDOG_BITE_THOLD pre-lock write did not land: entry=0x{bite_entry:08x} "
            f"wrote=0x{bite_pre:08x} read=0x{bite_rb:08x}",
        )
        self.logger.info(
            "CHK-NONVAC PASS: pre-lock writes landed: WDOG_BARK_THOLD 0x%08x -> 0x%08x "
            "(wrote 0x%08x), WDOG_BITE_THOLD 0x%08x -> 0x%08x (wrote 0x%08x)",
            bark_entry,
            bark_rb,
            bark_pre,
            bite_entry,
            bite_rb,
            bite_pre,
        )

        # WDOG_REGWEN.regwen resets to 1 (aon_timer.hjson:248) and nothing above
        # writes it, so it reads 1 before the lock write; the write of 0 is then the
        # only step that can clear it.
        regwen_pre = await self.wdt.read(WDOG_REGWEN)
        await self._grade(
            (regwen_pre & _REGWEN_MASK) == _REGWEN_MASK,
            "CHK-REGWEN-LOCK",
            f"precondition: WDOG_REGWEN.regwen before the lock write=0x"
            f"{regwen_pre & _REGWEN_MASK:x} expected 0x{_REGWEN_MASK:x} (read 0x{regwen_pre:08x})",
        )
        # Lock the WDOG config (writing 0 to WDOG_REGWEN latches the lock).
        await self.wdt.write(WDOG_REGWEN, 0)
        regwen = await self.wdt.read(WDOG_REGWEN)
        await self._grade(
            (regwen & _REGWEN_MASK) == 0,
            "CHK-REGWEN-LOCK",
            f"WDOG_REGWEN.regwen did not clear on a write of 0 (read 0x{regwen:08x})",
        )
        if regwen & ~_REGWEN_MASK:
            self.logger.info("OBS-WDT-RSVD: reg=WDOG_REGWEN raw=0x%08x", regwen)

        # CHK-REGWEN-LOCK: a write of a value other than the pre-lock value is
        # ignored on each threshold; the readback is the whole pre-lock value.
        chk = "CHK-REGWEN-LOCK"
        bark_try = self.cfg_wdt.bark_postlock
        bite_try = self.lock_draws.bite_postlock
        await self._grade(
            bark_try != bark_pre and bite_try != bite_pre,
            chk,
            f"CTRL-MISSING locked-write values equal the pre-lock values (bark 0x{bark_try:08x}, "
            f"bite 0x{bite_try:08x}); an ignored write could not be told from a landed one",
        )
        # The window opens one clk_i edge before the first locked write, so the
        # write and its readback both sample with it open.
        await ClockCycles(cocotb.top.clk_i, 1)
        open_graded_window(TEST, self.logger)
        try:
            await ClockCycles(cocotb.top.clk_i, 1)
            resp = await self.wdt.write_tolerant(WDOG_BARK_THOLD, bark_try)
            bark_post = await self.wdt.read(WDOG_BARK_THOLD)
            await self._grade(
                bark_post == bark_pre,
                chk,
                f"reg=WDOG_BARK_THOLD changed under the lock: pre=0x{bark_pre:08x} "
                f"wrote=0x{bark_try:08x} read=0x{bark_post:08x} resp={resp}",
            )
            resp_bite = await self.wdt.write_tolerant(WDOG_BITE_THOLD, bite_try)
            bite_post = await self.wdt.read(WDOG_BITE_THOLD)
            await self._grade(
                bite_post == bite_pre,
                chk,
                f"reg=WDOG_BITE_THOLD changed under the lock: pre=0x{bite_pre:08x} "
                f"wrote=0x{bite_try:08x} read=0x{bite_post:08x} resp={resp_bite}",
            )
            # Two more clk_i edges with the window open, so the close cannot race
            # the sampler at the last readback.
            await ClockCycles(cocotb.top.clk_i, 2)
        finally:
            await NextTimeStep()
            close_graded_window(self.logger)
        self.logger.info(
            "CHK-REGWEN-LOCK PASS: WDOG_REGWEN.regwen before the lock write=0x%x expected 0x%x, "
            "after=0x%08x; locked writes answered on the bus and "
            "ignored: WDOG_BARK_THOLD wrote 0x%08x read 0x%08x (pre-lock 0x%08x), "
            "WDOG_BITE_THOLD wrote 0x%08x read 0x%08x (pre-lock 0x%08x)",
            regwen_pre & _REGWEN_MASK,
            _REGWEN_MASK,
            regwen,
            bark_try,
            bark_post,
            bark_pre,
            bite_try,
            bite_post,
            bite_pre,
        )
        self.logger.info(
            "OBS-WDT-LOCK-RESP: locked-write response WDOG_BARK_THOLD=%d WDOG_BITE_THOLD=%d; "
            "the specification states no response code, not graded",
            resp,
            resp_bite,
        )

        # CHK-REGWEN-SCOPE: the lock covers WDOG_CTRL / WDOG_BARK_THOLD /
        # WDOG_BITE_THOLD only. The scope is read from the OpenTitan register
        # description (aon_timer.hjson, the source aon_timer_reg_top.sv is
        # generated from) via aon_timer_regwen_gates, not from the generated RTL,
        # so a hand-edited src_regwen_i disagrees with this check instead of
        # defining it. The WKUP configuration and WDOG_COUNT must therefore still
        # accept writes while the watchdog thresholds are locked -- a lock wired to
        # the whole block would freeze the wakeup timer and the pet path with it.
        gated = aon_timer_regwen_gates("WDOG_REGWEN")
        await self._grade(
            gated == {"WDOG_CTRL", "WDOG_BARK_THOLD", "WDOG_BITE_THOLD"},
            "CHK-REGWEN-SCOPE",
            f"aon_timer.hjson gates {sorted(gated)} behind "
            "WDOG_REGWEN; this check walks the three watchdog configuration "
            "registers and probes WKUP_THOLD_LO / WDOG_COUNT as ungated",
        )
        for ungated in ("WKUP_THOLD_LO", "WDOG_COUNT"):
            await self._grade(
                ungated not in gated,
                "CHK-REGWEN-SCOPE",
                f"{ungated} is gated by WDOG_REGWEN in "
                "aon_timer.hjson, so probing it as still-writable is wrong",
            )
        thold_val = self.cfg_wdt.postlock_wkup_thold
        await self.wdt.write(WKUP_THOLD_LO, thold_val)
        thold_rb = await self.wdt.read(WKUP_THOLD_LO)
        await self._grade(
            thold_rb == thold_val,
            "CHK-REGWEN-SCOPE",
            f"WKUP_THOLD_LO write blocked by the WDOG lock (0x{thold_rb:08x} != 0x{thold_val:08x})",
        )
        # WDOG_COUNT is a FREE-RUNNING counter and WDOG_CTRL is enabled from the
        # pet check -- WDOG_CTRL is itself REGWEN-locked, so it cannot be turned
        # off here. That rules out proving the write by RAISING the counter: it
        # reaches any small target on its own, so a write the lock wrongly blocked
        # would still be seen to "land", and a target near the seeded bark
        # threshold trips a bark instead.
        #
        # Prove the write by LOWERING the counter, which free running can never
        # do. Let it climb past a literal floor first -- the non-vacuity anchor,
        # which does not move with any seeded value -- then write zero and require
        # the readback to fall below the value held just before the write. A
        # blocked write leaves the counter at or above that value, still climbing.
        ran, pre_val = await self._poll_at_least(
            WDOG_COUNT,
            _COUNT_RUN_FLOOR,
            timeout_cycles=400 * self._tick,
            step=4 * self._tick,
        )
        await self._grade(
            ran,
            "CHK-REGWEN-SCOPE",
            f"WDOG_COUNT never reached {_COUNT_RUN_FLOOR} with the "
            f"watchdog enabled (read 0x{pre_val:08x}) -- the counter is not running, so "
            f"the write test below would be vacuous",
        )
        await self.wdt.write(WDOG_COUNT, 0)
        landed, count_rb = await self._poll_at_most(
            WDOG_COUNT, pre_val - 1, timeout_cycles=40 * self._tick, step=4 * self._tick
        )
        await self._grade(
            landed,
            "CHK-REGWEN-SCOPE",
            f"WDOG_COUNT write blocked by the WDOG lock -- the counter "
            f"never fell below the 0x{pre_val:08x} it held before the write "
            f"(read 0x{count_rb:08x})",
        )
        await self.wdt.write(WDOG_COUNT, 0)  # pet again: leave the watchdog far from bark
        self.logger.info(
            "CHK-REGWEN-SCOPE PASS: with WDOG_REGWEN=0, WKUP_THOLD_LO took 0x%08x and "
            "WDOG_COUNT fell from 0x%08x to 0x%08x on a write the lock did not block "
            "-- the lock covers the watchdog config only",
            thold_rb,
            pre_val,
            count_rb,
        )
