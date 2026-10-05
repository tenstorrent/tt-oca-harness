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

Ports OCAH `sep_clock_uvm_aon_timer_operation_test` (counter advance),
`wdt_cfg_lock_test` (WDOG_REGWEN lock), `wdt_wkup_timer_test` (wakeup timer) and
`wdt_pet_reset_test`. This test reads every counter frontdoor and clears with a
full RW1C; the OCAH test reads WDOG_COUNT by backdoor. Distinct from
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
from cocotb.triggers import ClockCycles
from env.sep_spec_tables import aon_timer_regwen_gates, aon_timer_wkup_ticks_per_count
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL
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
        await self._chk_intr_test()
        await self._chk_wdog_pet()
        await self._chk_reference_counter()
        await self._chk_regwen_lock_and_nonvac()
        # No CHK-ALL summary line: every facet above logs its own PASS, and a plan
        # row keyed on a bare summary string would record coverage with no checker
        # behind it.

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
        assert second > first, (
            f"CHK-REFCNT-RUNS FAIL: REFERENCE_COUNTER did not advance across a "
            f"400-cycle window ({first} -> {second}). The counter runs on "
            "clk_ref_i and resynchronises onto clk_i; a reference clock that is "
            "not running, or a CDC that never hands the value over, both read as "
            "a stable count"
        )
        self.logger.info(
            "CHK-REFCNT-RUNS PASS: REFERENCE_COUNTER %d -> %d across 400 core "
            "cycles, so the clk_ref_i counter and its crossing onto clk_i are live",
            first,
            second,
        )

        # CHK-REFCNT-LOAD is deliberately NOT claimed here. A software load of
        # this counter can be lost when clk_i runs far faster than clk_ref_i.
        # This bench drives clk_i at 1.25 ns and clk_ref_i at 10 ns. The update
        # crosses on a depth-1 async FIFO; prim_refclk_count_w_cdc.sv states that
        # an update that arrives before the previous one has crossed is "dropped
        # with no error indication", and the guard assertion in that primitive
        # (CntUpdateAccepted_A) is compiled out of this build by
        # COMMON_CELLS_ASSERTS_OFF, so the loss is silent. Claiming the load
        # needs a measurement at this ratio.

    async def _chk_wkup_count(self) -> None:
        """CHK-WKUP-COUNT: WKUP_COUNT advances on clk_wdt with a high (non-expiring) thold."""
        await self.wdt.write(WKUP_CTRL, 0)  # disable while configuring
        await self.wdt.write(WKUP_COUNT_HI, 0)
        await self.wdt.write(WKUP_COUNT_LO, 0)
        await self.wdt.write(WKUP_THOLD_HI, 0)
        await self.wdt.write(
            WKUP_THOLD_LO, self.cfg_wdt.wkup_high_thold
        )  # large: won't expire here
        await self.wdt.write(WKUP_CTRL, WKUP_ENABLE)  # prescaler=0
        count1 = await self.wdt.read(WKUP_COUNT_LO)
        await ClockCycles(cocotb.top.clk_i, 60 * self._tick)  # ~60 wdt ticks
        count2 = await self.wdt.read(WKUP_COUNT_LO)
        assert count2 > count1, (
            f"WKUP_COUNT did not advance on clk_wdt: count1={count1} count2={count2}"
        )
        intr = await self.wdt.read(INTR_STATE)
        assert (intr & INTR_WKUP_EXPIRED) == 0, (
            f"CHK-WKUP-COUNT: high threshold expired in the count window "
            f"(INTR_STATE=0x{intr:08x}, count2={count2}, thold={self.cfg_wdt.wkup_high_thold})"
        )
        await self.wdt.write(INTR_TEST, INTR_TEST_WKUP_EXPIRED)
        forced = await self.wdt.read(INTR_STATE)
        assert forced & INTR_WKUP_EXPIRED, (
            f"CHK-WKUP-COUNT: INTR_STATE.wkup_expired stayed 0 after INTR_TEST (0x{forced:08x})"
        )
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)
        self.logger.info(
            "CHK-WKUP-COUNT PASS: WKUP_COUNT %d -> %d (advances on clk_wdt); "
            "INTR_STATE.wkup_expired stayed 0 under the high threshold",
            count1,
            count2,
        )

    async def _count_advance(self, prescaler: int, window_ticks: int) -> int:
        """Restart the WKUP counter with ``prescaler`` and return its advance over
        ``window_ticks`` clk_wdt ticks. The threshold stays high, so nothing expires."""
        await self.wdt.write(WKUP_CTRL, 0)  # disable while configuring
        await self.wdt.write(WKUP_COUNT_HI, 0)
        await self.wdt.write(WKUP_COUNT_LO, 0)
        await self.wdt.write(WKUP_THOLD_HI, 0)
        await self.wdt.write(WKUP_THOLD_LO, self.cfg_wdt.wkup_high_thold)
        await self.wdt.write(WKUP_CTRL, WKUP_ENABLE | (prescaler << WKUP_PRESCALER_SHIFT))
        start = await self.wdt.read(WKUP_COUNT_LO)
        await ClockCycles(cocotb.top.clk_i, window_ticks * self._tick)
        end = await self.wdt.read(WKUP_COUNT_LO)
        await self.wdt.write(WKUP_CTRL, 0)  # stop the counter before the readback is used
        return end - start

    async def _chk_wkup_prescale(self) -> None:
        """CHK-WKUP-PRESCALE: WKUP_CTRL.prescaler divides the wakeup count rate.

        The OpenTitan AON Timer Technical Specification (Wakeup timer; upstream
        OpenTitan documentation, not vendored in this tree) states "The
        number of cycles per tick is one more than the 12-bit WKUP_CTRL.prescaler
        field", so the counter advances once per ``prescaler + 1`` ticks. That rate
        is carried by sep_spec_tables.aon_timer_wkup_ticks_per_count, not read back
        from aon_timer_core.sv. Measured over the same window with prescaler=0 and
        prescaler=P, the divided advance must fit the spec bound; a prescaler that is
        decoded but not applied advances at the undivided rate and fails the bound.
        """
        presc = self.cfg_wdt.wkup_prescaler
        # Window sized from the programmed divisor so the divided run must tick.
        # A frozen counter then fails the lower bound; a prescaler that is
        # ignored fails the upper bound. Both bounds come from the divisor.
        window = 4 * aon_timer_wkup_ticks_per_count(presc)
        adv_fast = await self._count_advance(0, window)
        adv_slow = await self._count_advance(presc, window)
        # Nonvacuity against an independent literal: the undivided run must make real
        # progress, otherwise "the divided run counted less" proves nothing.
        assert adv_fast >= 20, (
            f"CHK-WKUP-PRESCALE: prescaler=0 advanced only {adv_fast} over {window} "
            f"clk_wdt ticks; the divided-rate bound below would be vacuous"
        )
        expected = window // aon_timer_wkup_ticks_per_count(presc)
        bound_lo = 1
        bound_hi = expected + 2
        assert adv_slow >= bound_lo, (
            f"CHK-WKUP-PRESCALE: prescaler={presc} advanced {adv_slow} over {window} "
            f"clk_wdt ticks; a frozen wakeup counter still satisfies an upper bound"
        )
        assert adv_slow <= bound_hi, (
            f"CHK-WKUP-PRESCALE: prescaler={presc} advanced {adv_slow} over {window} "
            f"clk_wdt ticks, above the divided bound {bound_hi} (prescaler not applied?)"
        )
        assert adv_slow < adv_fast, (
            f"CHK-WKUP-PRESCALE: divided advance {adv_slow} is not below the "
            f"undivided advance {adv_fast}"
        )
        self.logger.info(
            "CHK-WKUP-PRESCALE PASS: WKUP_COUNT advanced %d ticks with prescaler=0 and "
            "%d with prescaler=%d over the same %d-tick window (bounds %d..%d)",
            adv_fast,
            adv_slow,
            presc,
            window,
            bound_lo,
            bound_hi,
        )

    async def _chk_wkup_expire(self) -> None:
        """CHK-WKUP-EXPIRE: small thold -> INTR_STATE.wkup_expired sets, then W1C -> 0."""
        await self.wdt.write(WKUP_CTRL, 0)  # disable
        await self.wdt.write(WKUP_COUNT_HI, 0)
        await self.wdt.write(WKUP_COUNT_LO, 0)
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)  # clear any stale status
        await self.wdt.write(WKUP_THOLD_HI, 0)
        await self.wdt.write(
            WKUP_THOLD_LO, self.cfg_wdt.wkup_thold
        )  # small: expires within poll budget
        await self.wdt.write(WKUP_CTRL, WKUP_ENABLE)
        ok, val = await self._poll_bit_set(
            INTR_STATE, INTR_WKUP_LSB, timeout_cycles=300 * self._tick, step=4 * self._tick
        )
        assert ok, f"WKUP_COUNT>=THOLD never set INTR_STATE.wkup_expired (INTR_STATE=0x{val:08x})"
        self.logger.info("CHK-WKUP-EXPIRE PASS (set): INTR_STATE.wkup_expired=1 (0x%08x)", val)
        await self.wdt.write(WKUP_CTRL, 0)  # disable the counter

        # CHK-WKUP-CAUSE: the wakeup-request status WKUP_CAUSE.cause is a distinct sticky
        # bit (set by HW on wkup expiry), separate from INTR_STATE. It is level-held while
        # WKUP_COUNT >= WKUP_THOLD, so it reads set here (condition still true); to clear it
        # we first remove the condition (reset WKUP_COUNT) then write 0 (not W1C).
        cause = await self.wdt.read(WKUP_CAUSE)
        assert cause & WKUP_CAUSE_BIT, f"WKUP_CAUSE.cause not set after wkup expiry (0x{cause:08x})"
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
        assert low and cnt_hi == 0, (
            f"WKUP_COUNT did not read back below WKUP_THOLD={self.cfg_wdt.wkup_thold} "
            f"after the reset write (HI=0x{cnt_hi:08x} LO=0x{cnt_lo:08x})"
        )
        # Hold for the same budget the write-0 clear below is given. A level-only
        # cause would drop within it, as the write-0 clear must.
        await ClockCycles(cocotb.top.clk_i, clear_budget)
        # Sticky: dropping the count must leave the cause set, otherwise the write-0
        # below cannot be blamed for the clear.
        cause_held = await self.wdt.read(WKUP_CAUSE)
        assert cause_held & WKUP_CAUSE_BIT, (
            f"WKUP_CAUSE.cause cleared when COUNT was reset (0x{cause_held:08x}); "
            f"the write-0 clear would then be unattributed"
        )
        # OpenTitan aon_timer WKUP_CAUSE: SW writes 0 to acknowledge/clear the cause.
        await self.wdt.write(WKUP_CAUSE, 0)
        # WKUP_CAUSE is AON-domain (clk_aon=clk_wdt): the clear settles over a few clk_wdt
        # cycles via the register CDC, so poll rather than read back immediately.
        ccleared, cpost = await self._poll_bit_clear(
            WKUP_CAUSE, WKUP_CAUSE_LSB, timeout_cycles=clear_budget, step=4 * self._tick
        )
        assert ccleared, (
            f"WKUP_CAUSE.cause not cleared after condition removal + write 0 (0x{cpost:08x})"
        )
        self.logger.info(
            "CHK-WKUP-CAUSE PASS: wakeup-request set on expiry, cleared -> 0 (0x%08x)", cpost
        )

        # CHK-WKUP-EXPIRE (RW1C): INTR_STATE.wkup_expired is an edge-latched sticky -> W1C clears
        # it (the counter is already reset/disabled, so it cannot re-set).
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)  # W1C
        post = await self.wdt.read(INTR_STATE)
        assert (post & INTR_WKUP_EXPIRED) == 0, (
            f"INTR_STATE.wkup_expired not cleared by W1C (0x{post:08x})"
        )
        self.logger.info(
            "CHK-WKUP-EXPIRE PASS (RW1C): W1C cleared wkup_expired -> 0 (0x%08x)", post
        )

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
        assert (pre & INTR_WKUP_EXPIRED) == 0, (
            f"CHK-INTR-TEST: INTR_STATE.wkup_expired already set before the force "
            f"(0x{pre:08x}); the set below would be unattributed"
        )
        await self.wdt.write(INTR_TEST, INTR_TEST_WKUP_EXPIRED)
        ok, val = await self._poll_bit_set(
            INTR_STATE, INTR_WKUP_LSB, timeout_cycles=100 * self._tick, step=4 * self._tick
        )
        assert ok, f"CHK-INTR-TEST: INTR_TEST did not set wkup_expired (INTR_STATE=0x{val:08x})"
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)  # W1C
        post = await self.wdt.read(INTR_STATE)
        assert (post & INTR_WKUP_EXPIRED) == 0, (
            f"CHK-INTR-TEST: W1C did not clear the forced wkup_expired (0x{post:08x})"
        )
        self.logger.info(
            "CHK-INTR-TEST PASS: INTR_TEST forced INTR_STATE.wkup_expired (0x%08x) with the "
            "wakeup counter off, and W1C cleared it (0x%08x)",
            val,
            post,
        )

    async def _chk_wdog_pet(self) -> None:
        """CHK-WDOG-PET: WDOG_COUNT advances, then write 0 (pet) resets it to ~0."""
        # REGWEN is 1 at reset (unlocked); set high thresholds so no bark/bite fires.
        await self.wdt.write(WDOG_BARK_THOLD, 0x00FF_FFFF)
        await self.wdt.write(WDOG_BITE_THOLD, 0x00FF_FFFF)
        await self.wdt.write(WDOG_COUNT, 0)
        await self.wdt.write(WDOG_CTRL, WDOG_ENABLE)
        # Run long enough that the pre-pet count dominates the CDC tolerance. A window
        # short enough to leave the count near the tolerance cannot distinguish "the pet
        # reset the counter" from "the pet was ignored", so the floor below is what
        # gives the comparison meaning.
        await ClockCycles(cocotb.top.clk_i, 1200 * self._tick)
        count1 = await self.wdt.read(WDOG_COUNT)
        assert count1 >= 0x400, (
            f"WDOG_COUNT only reached {count1} in the pre-pet window; it must exceed the "
            f"CDC tolerance by a wide margin or the pet check below is vacuous"
        )
        await self.wdt.write(WDOG_COUNT, 0)  # pet
        count2 = await self.wdt.read(WDOG_COUNT)
        assert count2 <= 0x100, (
            f"WDOG_COUNT not reset by pet: was {count1}, after pet {count2} (>0x100 CDC tol)"
        )
        assert count2 < count1 // 8, (
            f"WDOG_COUNT after pet ({count2}) is not clearly below the pre-pet count "
            f"({count1}) -- consistent with the pet being ignored"
        )
        self.logger.info("CHK-WDOG-PET PASS: WDOG_COUNT %d -> pet -> %d (reset)", count1, count2)

    async def _chk_regwen_lock_and_nonvac(self) -> None:
        """CHK-NONVAC + CHK-REGWEN-LOCK: a pre-lock WDOG_BARK_THOLD write lands; after
        WDOG_REGWEN=0 the same register is locked (write ignored, readback unchanged)."""
        # CHK-NONVAC: REGWEN still 1 -> the write lands (proves the lock check below is
        # not always-true).
        pre_val = self.cfg_wdt.bark_prelock
        await self.wdt.write(WDOG_BARK_THOLD, pre_val)
        pre = await self.wdt.read(WDOG_BARK_THOLD)
        assert pre == pre_val, (
            f"pre-lock WDOG_BARK_THOLD write did not land (0x{pre:08x} != 0x{pre_val:08x})"
        )
        self.logger.info("CHK-NONVAC PASS: pre-lock WDOG_BARK_THOLD write landed (0x%08x)", pre)

        # Lock the WDOG config (writing 0 to WDOG_REGWEN latches the lock).
        await self.wdt.write(WDOG_REGWEN, 0)
        regwen = await self.wdt.read(WDOG_REGWEN)
        assert (regwen & 1) == 0, f"WDOG_REGWEN did not lock (regwen=0x{regwen:08x})"

        # CHK-REGWEN-LOCK: a new (distinct) WDOG_BARK_THOLD write is ignored (tolerate a
        # possible SLVERR reject); readback stays at the pre-lock value.
        resp = await self.wdt.write_tolerant(WDOG_BARK_THOLD, self.cfg_wdt.bark_postlock)
        post = await self.wdt.read(WDOG_BARK_THOLD)
        assert post == pre_val, (
            f"WDOG_BARK_THOLD changed after REGWEN lock: 0x{post:08x} (expected 0x{pre_val:08x}, "
            f"write resp={resp})"
        )
        bite_pre = await self.wdt.read(WDOG_BITE_THOLD)
        resp_bite = await self.wdt.write_tolerant(WDOG_BITE_THOLD, self.cfg_wdt.bark_postlock)
        bite_post = await self.wdt.read(WDOG_BITE_THOLD)
        assert bite_post == bite_pre, (
            f"WDOG_BITE_THOLD changed after REGWEN lock: 0x{bite_post:08x} "
            f"(expected 0x{bite_pre:08x}, write resp={resp_bite})"
        )
        self.logger.info(
            "CHK-REGWEN-LOCK PASS: post-lock WDOG_BARK_THOLD and WDOG_BITE_THOLD writes "
            "ignored, bark stays 0x%08x bite stays 0x%08x (write resp=%d/%d)",
            post,
            bite_post,
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
        assert gated == {"WDOG_CTRL", "WDOG_BARK_THOLD", "WDOG_BITE_THOLD"}, (
            f"CHK-REGWEN-SCOPE: aon_timer.hjson gates {sorted(gated)} behind "
            "WDOG_REGWEN; this check walks the three watchdog configuration "
            "registers and probes WKUP_THOLD_LO / WDOG_COUNT as ungated"
        )
        for ungated in ("WKUP_THOLD_LO", "WDOG_COUNT"):
            assert ungated not in gated, (
                f"CHK-REGWEN-SCOPE: {ungated} is gated by WDOG_REGWEN in "
                "aon_timer.hjson, so probing it as still-writable is wrong"
            )
        thold_val = self.cfg_wdt.postlock_wkup_thold
        await self.wdt.write(WKUP_THOLD_LO, thold_val)
        thold_rb = await self.wdt.read(WKUP_THOLD_LO)
        assert thold_rb == thold_val, (
            f"CHK-REGWEN-SCOPE: WKUP_THOLD_LO write blocked by the WDOG lock "
            f"(0x{thold_rb:08x} != 0x{thold_val:08x})"
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
        assert ran, (
            f"CHK-REGWEN-SCOPE: WDOG_COUNT never reached {_COUNT_RUN_FLOOR} with the "
            f"watchdog enabled (read 0x{pre_val:08x}) -- the counter is not running, so "
            f"the write test below would be vacuous"
        )
        await self.wdt.write(WDOG_COUNT, 0)
        landed, count_rb = await self._poll_at_most(
            WDOG_COUNT, pre_val - 1, timeout_cycles=40 * self._tick, step=4 * self._tick
        )
        assert landed, (
            f"CHK-REGWEN-SCOPE: WDOG_COUNT write blocked by the WDOG lock -- the counter "
            f"never fell below the 0x{pre_val:08x} it held before the write "
            f"(read 0x{count_rb:08x})"
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
