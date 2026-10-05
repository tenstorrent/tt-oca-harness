# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC persistent-failure alert to PIC source 16, then W1C-clear.

no_cpu / +skip_fuse_sense / +esrc_noise_force. RAND-NONE. A short
health-test window plus stuck forced noise accumulates one failing
window and trips ``ALERT_THRESHOLD``. Proves ``MAIN_SM_STATUS.ALERT``,
``INTR_STATUS.PERSISTENT_FAILURE``, and ``sep_internal_interrupts[15]``
(PIC source 16), then leaves AlertHang and W1C-clears both bits to 0.
Health-test quality stays out of scope.

The same trip also reads the alert bookkeeping: ANY_FAIL_COUNT is denominated in
failing windows, ALERT_FAIL_COUNTS attributes the trip to the repetition lane,
HEALTH_TEST_STATUS latches the failing tests, and MAIN_SM_STATUS.ERR must stay 0
so PERSISTENT_FAILURE is attributable to AlertHang rather than to a counter or
state fault. An opening INTR_TEST sweep, before the trip, drives each interrupt
source the RDL defines on its own, which proves the aggregate slot per source independently of
any real failure.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_alert_seq import (
    ALERT_MASK,
    ANY_FAIL_SLACK,
    ERR_MASK,
    HEALTH_RSVD_MASK,
    INTR_SOURCES,
    IRQ_AGG_IDX,
    PF_MASK,
    TRIP_THRESHOLD,
    SepEsrcAlert,
)

_TRIP_TIMEOUT_CYCLES = 80_000
_TRIP_POLL_EVERY = 64


@pyuvm.test()
class sep_esrc_alert_delivery_test(sep_base_test):
    """Trip persistent failure, claim PIC source 16, W1C-clear."""

    def _irq_bit(self) -> int:
        vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << IRQ_AGG_IDX)
        return (vec >> IRQ_AGG_IDX) & 1

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        # Routing only: this leaf holds the raw noise at a constant below to
        # trip the persistent health-test failure, so a toggling generator is
        # the opposite of what it needs.
        await self.assert_noise_force_routed()
        esrc = SepEsrcAlert(self)

        sm = await esrc.read_main_sm()
        st = await esrc.read_intr()
        irq = self._irq_bit()
        assert (sm & ALERT_MASK) == 0 and (st & PF_MASK) == 0 and irq == 0, (
            f"CHK-NO-ALERT FAIL: already alert sm=0x{sm:08x} st=0x{st:08x} irq={irq}"
        )
        self.logger.info(
            "CHK-NO-ALERT PASS: MAIN_SM_STATUS.ALERT=0 INTR_STATUS.PF=0 "
            "sep_internal_interrupts[%d]=0 before the trip",
            IRQ_AGG_IDX,
        )

        # INTR_TEST drives each source independently of the block's functional
        # state. Sweep before the trip: INTR_STATUS bits are re-driven every cycle
        # from their live cause, so once a real health-test failure is latched the
        # matching bit cannot clear on W1C. From the clean pre-trip state each
        # source must set only its own bit, raise the aggregate slot, and clear.
        await esrc.enable_all_irq()
        proven: list[str] = []
        for name, bm in INTR_SOURCES:
            # Each source starts from a dropped line, so its irq == 1 below is
            # its own and not one left high by the source before it.
            assert self._irq_bit() == 0, (
                f"CHK-INTR-TEST FAIL: sep_internal_interrupts[{IRQ_AGG_IDX}] already high "
                f"before the {name} pulse"
            )
            await esrc.pulse_intr_test(bm)
            st = await esrc.read_intr()
            irq = self._irq_bit()
            assert (st & bm) == bm, (
                f"CHK-INTR-TEST FAIL: {name} pulse left INTR_STATUS=0x{st:08x}, "
                f"expected bit 0x{bm:08x} set"
            )
            assert (st & ~bm & 0xFFFF_FFFF) == 0, (
                f"CHK-INTR-TEST FAIL: {name} pulse also set 0x{st & ~bm & 0xFFFF_FFFF:08x}; "
                f"sources are not independent"
            )
            assert irq == 1, (
                f"CHK-INTR-TEST FAIL: {name} set INTR_STATUS but "
                f"sep_internal_interrupts[{IRQ_AGG_IDX}]=0"
            )
            await esrc.w1c_intr_status(bm)
            st_after = await esrc.read_intr()
            assert (st_after & bm) == 0, (
                f"CHK-INTR-TEST FAIL: {name} did not clear on W1C "
                f"(INTR_STATUS=0x{st_after:08x}); a single-pulse source must not re-latch"
            )
            assert self._irq_bit() == 0, (
                f"CHK-INTR-TEST FAIL: {name} cleared INTR_STATUS but "
                f"sep_internal_interrupts[{IRQ_AGG_IDX}] stayed high"
            )
            proven.append(name)
        self.logger.info(
            "CHK-INTR-TEST PASS: all %d INTR_TEST sources set their own INTR_STATUS bit, "
            "raised PIC source 16 from a dropped line, and dropped it again on W1C: %s",
            len(proven),
            ", ".join(proven),
        )

        await esrc.enable_persistent_irq()
        await esrc.arm_failing_windows()

        dut = cocotb.top
        sm = st = 0
        irq = 0
        for cycle in range(_TRIP_TIMEOUT_CYCLES):
            dut.esrc_noise_ext_i.value = 0
            await RisingEdge(dut.clk_i)
            if cycle % _TRIP_POLL_EVERY != 0:
                continue
            sm = await esrc.read_main_sm()
            st = await esrc.read_intr()
            irq = self._irq_bit()
            if (sm & ALERT_MASK) and (st & PF_MASK) and irq:
                break
        else:
            raise AssertionError(
                f"CHK-ALERT FAIL: no persistent trip in {_TRIP_TIMEOUT_CYCLES} "
                f"cycles sm=0x{sm:08x} st=0x{st:08x} irq={irq}"
            )
        self.logger.info("CHK-ALERT PASS: MAIN_SM_STATUS.ALERT=1 after threshold")
        self.logger.info("CHK-PERSISTENT-FAILURE PASS: INTR_STATUS.PERSISTENT_FAILURE=1")
        self.logger.info(
            "CHK-PIC-16 PASS: sep_internal_interrupts[%d] (PIC source 16)=1", IRQ_AGG_IDX
        )

        # PERSISTENT_FAILURE is the OR of the AlertHang trip, a main-FSM error and
        # a counter-integrity error. With ERR still 0 the bit is attributable to the
        # threshold trip proved above.
        assert (sm & ERR_MASK) == 0, (
            f"CHK-SM-ERR-ZERO FAIL: MAIN_SM_STATUS.ERR set at the trip (0x{sm:08x}), so "
            f"PERSISTENT_FAILURE is not attributable to AlertHang"
        )
        self.logger.info(
            "CHK-SM-ERR-ZERO PASS: MAIN_SM_STATUS.ERR=0 at the trip, so "
            "PERSISTENT_FAILURE came from the alert threshold"
        )

        # entropy_source.rdl ALERT_SUMMARY_FAIL_COUNTS counts "consecutive
        # health-test windows containing any failure", so the counter is
        # denominated in failing WINDOWS. ALERT_FAIL_COUNTS counts the individual
        # per-test failures instead, so the sum of its lanes bounds
        # ANY_FAIL_COUNT from above. Both halves are needed: the lower bound alone
        # is implied by the alert comparator that already fired, and the upper
        # bound is what rejects a build that counts events where the register is
        # documented to count windows.
        any_fail = await esrc.read_any_fail_count()
        alert_counts = await esrc.read_alert_fail_counts()
        lane_pulses = sum(alert_counts.values())
        assert TRIP_THRESHOLD <= any_fail <= TRIP_THRESHOLD + ANY_FAIL_SLACK, (
            f"CHK-ANY-FAIL-WINDOWS FAIL: ANY_FAIL_COUNT={any_fail} outside "
            f"[{TRIP_THRESHOLD}, {TRIP_THRESHOLD + ANY_FAIL_SLACK}] at the trip; "
            f"per-lane pulses {alert_counts}"
        )
        assert lane_pulses >= any_fail, (
            f"CHK-ANY-FAIL-WINDOWS FAIL: per-lane fail pulses {lane_pulses} below "
            f"ANY_FAIL_COUNT={any_fail}; a failing window must carry at least one "
            f"failing lane ({alert_counts})"
        )
        self.logger.info(
            "CHK-ANY-FAIL-WINDOWS PASS: ANY_FAIL_COUNT=%d window(s) in "
            "[%d, %d], under %d per-lane fail pulses %s",
            any_fail,
            TRIP_THRESHOLD,
            TRIP_THRESHOLD + ANY_FAIL_SLACK,
            lane_pulses,
            alert_counts,
        )

        # Stuck noise with REPETITION_LIMIT=5 fails the repetition lane. Per
        # entropy_source.rdl two separate counters see that one pulse --
        # <lane>_TOTAL_FAILS counts since the last CTRL.MODULE_ENABLE rising
        # edge, and ALERT_FAIL_COUNTS counts for the current alert sequence only
        # -- so the total must cover the alert counter. The reverse does not
        # hold: an accepted passing window ends the alert sequence, so a lane's
        # alert counter can return to zero while its total keeps the history.
        totals = await esrc.read_total_fails()
        assert totals["REPCNT"] > 0, (
            f"CHK-FAIL-ATTRIB FAIL: REPCNT_TOTAL_FAILS={totals['REPCNT']} with stuck "
            f"noise and REPETITION_LIMIT=5; the trip was not attributed to the "
            f"repetition test (totals={totals})"
        )
        for lane, alert_count in alert_counts.items():
            assert totals[lane] >= alert_count, (
                f"CHK-FAIL-ATTRIB FAIL: {lane}_TOTAL_FAILS={totals[lane]} below "
                f"ALERT_FAIL_COUNTS.{lane}_FAIL_COUNT={alert_count}; the two counters "
                f"take the same fail pulse"
            )
        self.logger.info(
            "CHK-FAIL-ATTRIB PASS: totals %s cover alert counters %s", totals, alert_counts
        )

        # HEALTH_TEST_STATUS latches which tests failed and is W1C. The RDL
        # allocates repetition [0], APT [3], Markov high [4] and Markov low [5];
        # bits 1:2 and 6:7 are reserved and must never latch. The twelve
        # per-generator status registers carry the same allocation.
        ht_status = await esrc.read_health_status()
        assert ht_status != 0, (
            "CHK-HT-STATUS FAIL: HEALTH_TEST_STATUS.HEALTH_STATUS latched no failing test "
            "while the alert was asserted"
        )
        assert (ht_status & HEALTH_RSVD_MASK) == 0, (
            f"CHK-HT-STATUS FAIL: HEALTH_TEST_STATUS=0x{ht_status:02x} latched a "
            f"reserved bit (mask 0x{HEALTH_RSVD_MASK:02x})"
        )
        gen_health = await esrc.read_generator_health()
        for n, status in enumerate(gen_health):
            assert (status & HEALTH_RSVD_MASK) == 0, (
                f"CHK-GEN-HEALTH FAIL: GENERATOR_{n}_HEALTH_STATUS=0x{status:02x} "
                f"latched a reserved bit (mask 0x{HEALTH_RSVD_MASK:02x})"
            )
        assert any(gen_health), (
            "CHK-GEN-HEALTH FAIL: no per-generator health-status register latched a "
            "failing lane while the aggregate HEALTH_TEST_STATUS reads "
            f"0x{ht_status:02x} and the alert is asserted"
        )
        self.logger.info(
            "CHK-GEN-HEALTH PASS: twelve per-generator health-status bytes %s latch "
            "the failing lanes and no reserved bit",
            [f"0x{v:02x}" for v in gen_health],
        )
        self.logger.info(
            "CHK-HT-STATUS latched 0x%02x during the alert; W1C is proven after "
            "AlertHang is left, where no new failure can re-latch it",
            ht_status,
        )

        await esrc.leave_alert_hang()
        sm_before_w1c = await esrc.read_main_sm()
        st_before_w1c = await esrc.read_intr()
        assert (sm_before_w1c & ALERT_MASK) and (st_before_w1c & PF_MASK), (
            f"CHK-W1C FAIL: MODULE_ENABLE=0 already cleared ALERT/PF "
            f"(sm=0x{sm_before_w1c:08x} st=0x{st_before_w1c:08x}); "
            "the W1C write would have been a no-op"
        )
        await esrc.w1c_alert()
        sm = await esrc.read_main_sm()
        st = await esrc.read_intr()
        irq = self._irq_bit()
        assert (sm & ALERT_MASK) == 0, f"CHK-W1C FAIL: MAIN_SM_STATUS.ALERT still 1 (0x{sm:08x})"
        assert (st & PF_MASK) == 0, (
            f"CHK-W1C FAIL: INTR_STATUS.PERSISTENT_FAILURE still 1 (0x{st:08x})"
        )
        assert irq == 0, "CHK-W1C FAIL: PIC source 16 still asserted"
        self.logger.info(
            "CHK-W1C PASS: ALERT and PERSISTENT_FAILURE read back 0; sep_internal_interrupts[%d]=0",
            IRQ_AGG_IDX,
        )

        # entropy_source.rdl: HEALTH_TEST_CTRL.ENABLE "Disabling a test clears its
        # state", and HEALTH_TEST_STATUS is a sticky latch, "Write one to clear."
        # With every test disabled no fail signal can re-latch a bit, so the latch
        # still holds the trip bits before the write and reads 0 after it.
        await esrc.disable_health_tests()
        ht_live = await esrc.read_health_status()
        assert (ht_live & ht_status) == ht_status, (
            f"CHK-HT-STATUS FAIL: HEALTH_TEST_STATUS lost trip bits without a write "
            f"(0x{ht_status:02x} at the trip, 0x{ht_live:02x} after ENABLE=0)"
        )
        await esrc.w1c_health_status(ht_live)
        ht_cleared = await esrc.read_health_status()
        assert ht_cleared == 0, (
            f"CHK-HT-STATUS FAIL: W1C of 0x{ht_live:02x} with every health test "
            f"disabled reads 0x{ht_cleared:02x}, expected 0x00"
        )
        self.logger.info(
            "CHK-HT-STATUS PASS: HEALTH_STATUS latched 0x%02x at the trip, held 0x%02x "
            "after ENABLE=0, and W1C of every latched bit reads back 0x00",
            ht_status,
            ht_live,
        )
