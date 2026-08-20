# SPDX-License-Identifier: Apache-2.0
"""WDT / AON-timer internals.

no_cpu host-AXI CSR test of the SEP WDT aon_timer internals separate from the
bark/bite/NMI story: the WKUP (wakeup) timer + its INTR_STATE.wkup_expired RW1C
status, the WDOG counter advance + pet, and the WDOG_REGWEN config-lock. The WKUP
interrupt OUTPUT is unused in sep, so the expiry is proven via the polled
INTR_STATE.wkup_expired CSR bit (full RW1C clear) -- no ISR/NMI needed.

reference refs: clock sep_clock_uvm_aon_timer_operation_test (: counter advance
+ bark), fw wdt_cfg_lock_test (WDOG_REGWEN lock), wdt_wkup_timer_test (:
AON wakeup timer), wdt_pet_reset_test. Mapping:
COVERED_STRONGER -- frontdoor CSR + full RW1C clear (the reference suite reads WDOG_COUNT via
uvm_hdl_read). Distinct from the bark->NMI vec/lock path and the bark/pet/disable/
re-bark + bite->wdt_timer_rst_req_o path: this test proves the OTHER aon_timer
internals (WKUP timer, REGWEN config-lock, plain counter/pet), NOT bark/bite/NMI.

The WDT counters run on clk_wdt (~1000x slower than the core clock here), so the
counter waits/poll budgets are sized in core cycles accordingly. The block is
always clocked (no CLOCK_GATE_CTRL ungate). no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_wdt_aon_seq import (
    SepWdtAon, RESP_OKAY,
    WKUP_CTRL, WKUP_THOLD_HI, WKUP_THOLD_LO, WKUP_COUNT_HI, WKUP_COUNT_LO,
    WDOG_REGWEN, WDOG_CTRL, WDOG_BARK_THOLD, WDOG_BITE_THOLD, WDOG_COUNT,
    INTR_STATE, WKUP_CAUSE, WKUP_ENABLE, WDOG_ENABLE, INTR_WKUP_EXPIRED,
    SepWdtCfg,
)

# WKUP_CAUSE.cause bit (wakeup-request status). RTL finding: despite the RDL
# onwrite=woclr label, the cause is acknowledged/cleared by WRITING 0 (firmware-
# aligned), AFTER the wakeup condition (count>=thold) is removed -- it is level-held
# and AON-domain (the clear settles over a few clk_wdt cycles).
WKUP_CAUSE_BIT = 1 << 0

# How much faster than the silicon 1000x ratio we run clk_wdt for this CSR test
# (sim-timing knob): clk_wdt = WDT_CLK_RATIO x the core period -- still
# slower than the core (a valid CDC ratio) so the aon_timer clk_i->clk_aon register
# CDC (prim_reg_cdc busy-stall on a WKUP_CTRL/WDOG enable write) and the counters
# resolve within the AXI timeout, while still exercising the count/expiry/lock paths.
WDT_CLK_RATIO = 8


@pyuvm.test()
class sep_wdt_aon_timer_internals_test(sep_base_test):
    """WKUP timer (count + expiry RW1C), WDOG pet, and WDOG_REGWEN config-lock."""

    async def _poll_bit_set(self, addr: int, bit: int, *, timeout_cycles: int,
                            step: int) -> tuple[bool, int]:
        """Poll addr until (val>>bit)&1 == 1 or timeout; FAIL-checked by the caller."""
        waited = 0
        val = 0
        while waited < timeout_cycles:
            val = await self.wdt.read(addr)
            if (val >> bit) & 1:
                return True, val
            await ClockCycles(cocotb.top.clk_i, step)
            waited += step
        return False, val

    async def _poll_bit_clear(self, addr: int, bit: int, *, timeout_cycles: int,
                              step: int) -> tuple[bool, int]:
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

    async def run_scenario(self) -> None:
        self.cfg_wdt = SepWdtCfg(self.random_seed())
        self.logger.info("WDT config: %s", self.cfg_wdt.summary())
        # Speed clk_wdt for this CSR test (see WDT_CLK_RATIO). Set before bring-up so
        # start_clocks picks it up. _tick = core cycles per clk_wdt tick.
        self.cfg.wdt_clk_period_ns = WDT_CLK_RATIO * self.cfg.sys_clk_period_ns
        self._tick = WDT_CLK_RATIO
        self.logger.info(
            "WDT sim-timing knob: clk_wdt=%dns (%dx core), _tick=%d core cycles",
            self.cfg.wdt_clk_period_ns, WDT_CLK_RATIO, self._tick,
        )
        await self.bring_up_no_cpu()
        self.wdt = SepWdtAon(self)

        await self._chk_wkup_count()
        await self._chk_wkup_expire()
        await self._chk_wdog_pet()
        await self._chk_regwen_lock_and_nonvac()
        self.logger.info("CHK-ALL PASS: WDT aon_timer WKUP count+expiry, WDOG pet, REGWEN lock")

    async def _chk_wkup_count(self) -> None:
        """CHK-WKUP-COUNT: WKUP_COUNT advances on clk_wdt with a high (non-expiring) thold."""
        await self.wdt.write(WKUP_CTRL, 0)                     # disable while configuring
        await self.wdt.write(WKUP_COUNT_HI, 0)
        await self.wdt.write(WKUP_COUNT_LO, 0)
        await self.wdt.write(WKUP_THOLD_HI, 0)
        await self.wdt.write(WKUP_THOLD_LO, self.cfg_wdt.wkup_high_thold)  # large: won't expire here
        await self.wdt.write(WKUP_CTRL, WKUP_ENABLE)           # prescaler=0
        count1 = await self.wdt.read(WKUP_COUNT_LO)
        await ClockCycles(cocotb.top.clk_i, 60 * self._tick)   # ~60 wdt ticks
        count2 = await self.wdt.read(WKUP_COUNT_LO)
        assert count2 > count1, (
            f"WKUP_COUNT did not advance on clk_wdt: count1={count1} count2={count2}"
        )
        self.logger.info("CHK-WKUP-COUNT PASS: WKUP_COUNT %d -> %d (advances on clk_wdt)", count1, count2)

    async def _chk_wkup_expire(self) -> None:
        """CHK-WKUP-EXPIRE: small thold -> INTR_STATE.wkup_expired sets, then W1C -> 0."""
        await self.wdt.write(WKUP_CTRL, 0)                     # disable
        await self.wdt.write(WKUP_COUNT_HI, 0)
        await self.wdt.write(WKUP_COUNT_LO, 0)
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)    # clear any stale status
        await self.wdt.write(WKUP_THOLD_HI, 0)
        await self.wdt.write(WKUP_THOLD_LO, self.cfg_wdt.wkup_thold)  # small: expires within poll budget
        await self.wdt.write(WKUP_CTRL, WKUP_ENABLE)
        ok, val = await self._poll_bit_set(
            INTR_STATE, 0, timeout_cycles=300 * self._tick, step=4 * self._tick
        )
        assert ok, f"WKUP_COUNT>=THOLD never set INTR_STATE.wkup_expired (INTR_STATE=0x{val:08x})"
        self.logger.info("CHK-WKUP-EXPIRE PASS (set): INTR_STATE.wkup_expired=1 (0x%08x)", val)
        await self.wdt.write(WKUP_CTRL, 0)                     # disable the counter

        # CHK-WKUP-CAUSE: the wakeup-request status WKUP_CAUSE.cause is a DISTINCT sticky
        # bit (set by HW on wkup expiry), separate from INTR_STATE. It is level-held while
        # WKUP_COUNT >= WKUP_THOLD, so it reads set NOW (condition still true); to clear it
        # we first remove the condition (reset WKUP_COUNT) then write 0 (not W1C).
        cause = await self.wdt.read(WKUP_CAUSE)
        assert cause & WKUP_CAUSE_BIT, f"WKUP_CAUSE.cause not set after wkup expiry (0x{cause:08x})"
        await self.wdt.write(WKUP_COUNT_HI, 0)                 # remove the wakeup condition
        await self.wdt.write(WKUP_COUNT_LO, 0)
        # OpenTitan aon_timer WKUP_CAUSE: SW writes 0 to acknowledge/clear the cause.
        await self.wdt.write(WKUP_CAUSE, 0)
        # WKUP_CAUSE is AON-domain (clk_aon=clk_wdt): the clear settles over a few clk_wdt
        # cycles via the register CDC, so poll rather than read back immediately.
        ccleared, cpost = await self._poll_bit_clear(
            WKUP_CAUSE, 0, timeout_cycles=100 * self._tick, step=4 * self._tick
        )
        assert ccleared, (
            f"WKUP_CAUSE.cause not cleared after condition removal + write 0 (0x{cpost:08x})"
        )
        self.logger.info("CHK-WKUP-CAUSE PASS: wakeup-request set on expiry, cleared -> 0 (0x%08x)", cpost)

        # CHK-WKUP-EXPIRE (RW1C): INTR_STATE.wkup_expired is an edge-latched sticky -> W1C clears
        # it (the counter is already reset/disabled, so it cannot re-set).
        await self.wdt.write(INTR_STATE, INTR_WKUP_EXPIRED)    # W1C
        post = await self.wdt.read(INTR_STATE)
        assert (post & INTR_WKUP_EXPIRED) == 0, (
            f"INTR_STATE.wkup_expired not cleared by W1C (0x{post:08x})"
        )
        self.logger.info("CHK-WKUP-EXPIRE PASS (RW1C): W1C cleared wkup_expired -> 0 (0x%08x)", post)

    async def _chk_wdog_pet(self) -> None:
        """CHK-WDOG-PET: WDOG_COUNT advances, then write 0 (pet) resets it to ~0."""
        # REGWEN is 1 at reset (unlocked); set high thresholds so no bark/bite fires.
        await self.wdt.write(WDOG_BARK_THOLD, 0x00FF_FFFF)
        await self.wdt.write(WDOG_BITE_THOLD, 0x00FF_FFFF)
        await self.wdt.write(WDOG_COUNT, 0)
        await self.wdt.write(WDOG_CTRL, WDOG_ENABLE)
        await ClockCycles(cocotb.top.clk_i, 60 * self._tick)
        count1 = await self.wdt.read(WDOG_COUNT)
        assert count1 > 0, f"WDOG_COUNT did not advance (={count1})"
        await self.wdt.write(WDOG_COUNT, 0)                    # pet
        count2 = await self.wdt.read(WDOG_COUNT)
        assert count2 <= 0x100, (
            f"WDOG_COUNT not reset by pet: was {count1}, after pet {count2} (>0x100 CDC tol)"
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
        assert pre == pre_val, f"pre-lock WDOG_BARK_THOLD write did not land (0x{pre:08x} != 0x{pre_val:08x})"
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
        self.logger.info(
            "CHK-REGWEN-LOCK PASS: post-lock WDOG_BARK_THOLD write ignored, stays 0x%08x "
            "(write resp=%d)", post, resp,
        )
