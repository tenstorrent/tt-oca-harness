# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC persistent-failure alert to PIC source 16, then W1C-clear.

no_cpu / +skip_fuse_sense / +esrc_noise_force. RAND-NONE. A short
health-test window plus stuck forced noise accumulates one failing
window and trips ``ALERT_THRESHOLD``. Proves ``MAIN_SM_STATUS.ALERT``,
``INTR_STATUS.PERSISTENT_FAILURE``, and ``sep_internal_interrupts[15]``
(PIC source 16), then leaves AlertHang and W1C-clears both bits to 0.
Health-test quality stays out of scope.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge

from sep_base_test import sep_base_test
from seq_lib.sep_esrc_alert_seq import (
    ALERT_MASK,
    IRQ_AGG_IDX,
    PF_MASK,
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
            "sep_internal_interrupts[%d]=0 before the trip", IRQ_AGG_IDX)

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
        self.logger.info(
            "CHK-ALERT PASS: MAIN_SM_STATUS.ALERT=1 after threshold")
        self.logger.info(
            "CHK-PERSISTENT-FAILURE PASS: INTR_STATUS.PERSISTENT_FAILURE=1")
        self.logger.info(
            "CHK-PIC-16 PASS: sep_internal_interrupts[%d] (PIC source 16)=1",
            IRQ_AGG_IDX)

        await esrc.leave_alert_hang()
        await esrc.w1c_alert()
        sm = await esrc.read_main_sm()
        st = await esrc.read_intr()
        irq = self._irq_bit()
        assert (sm & ALERT_MASK) == 0, (
            f"CHK-W1C FAIL: MAIN_SM_STATUS.ALERT still 1 (0x{sm:08x})"
        )
        assert (st & PF_MASK) == 0, (
            f"CHK-W1C FAIL: INTR_STATUS.PERSISTENT_FAILURE still 1 (0x{st:08x})"
        )
        assert irq == 0, "CHK-W1C FAIL: PIC source 16 still asserted"
        self.logger.info(
            "CHK-W1C PASS: ALERT and PERSISTENT_FAILURE read back 0; "
            "sep_internal_interrupts[%d]=0", IRQ_AGG_IDX)
