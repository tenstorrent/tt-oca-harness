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
state fault. A closing INTR_TEST sweep drives each interrupt source the RDL
defines on its own, which proves the aggregate slot per source independently of
any real failure.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_alert_seq import (
    ALERT_MASK,
    ERR_MASK,
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
        return (self.rd(cocotb.top.sep_internal_interrupts_probe_o) >> IRQ_AGG_IDX) & 1

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
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
                f"(INTR_STATUS=0x{st_after:08x}); a singlepulse source must not re-latch"
            )
            proven.append(name)
        assert len(proven) == 8, (
            f"CHK-INTR-TEST FAIL: proved {len(proven)} sources {proven}, expected the "
            f"8 interrupt sources entropy_source.rdl defines"
        )
        self.logger.info(
            "CHK-INTR-TEST PASS: all %d INTR_TEST sources set their own INTR_STATUS bit, "
            "raised PIC source 16, and cleared on W1C: %s",
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

        # ALERT_THRESHOLD is denominated in failing WINDOWS, not failure events:
        # ANY_FAIL_COUNT's event input is the once-per-window ht_fail_pulse. A build
        # that counted individual per-test fail pulses would over-count here.
        any_fail = await esrc.read_any_fail_count()
        assert any_fail >= TRIP_THRESHOLD, (
            f"CHK-ANY-FAIL-WINDOWS FAIL: ANY_FAIL_COUNT={any_fail} below the "
            f"ALERT_THRESHOLD={TRIP_THRESHOLD} that tripped the alert"
        )
        self.logger.info(
            "CHK-ANY-FAIL-WINDOWS PASS: ANY_FAIL_COUNT=%d failing window(s) >= ALERT_THRESHOLD=%d",
            any_fail,
            TRIP_THRESHOLD,
        )

        # Stuck noise with REPETITION_LIMIT=5 fails the repetition lane, so the
        # per-test attribution counter for that lane must be non-zero.
        repcnt_fails = await esrc.read_repcnt_fail_count()
        assert repcnt_fails > 0, (
            f"CHK-FAIL-ATTRIB FAIL: REPCNT_FAIL_COUNT={repcnt_fails} with stuck noise "
            f"and REPETITION_LIMIT=5; the trip was not attributed to the repetition test"
        )
        self.logger.info(
            "CHK-FAIL-ATTRIB PASS: REPCNT_FAIL_COUNT=%d attributes the trip to the repetition test",
            repcnt_fails,
        )

        # HEALTH_TEST_STATUS latches which tests failed and is W1C.
        ht_status = await esrc.read_health_status()
        assert ht_status != 0, (
            "CHK-HT-STATUS FAIL: HEALTH_TEST_STATUS.HEALTH_STATUS latched no failing test "
            "while the alert was asserted"
        )
        await esrc.w1c_health_status(ht_status)
        self.logger.info(
            "CHK-HT-STATUS PASS: HEALTH_STATUS latched 0x%02x during the alert", ht_status
        )

        await esrc.leave_alert_hang()
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
