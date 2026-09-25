# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_ac_extest_pulse_test.

EXTEST_PULSE (IR 0x06) selects the boundary-scan chain, which this bench loops
back without boundary cells. The chain's run_test_idle strobe is the
Run-Test/Idle decode the AC pulse launches on: one pulse across a DR scan, on
the return to Run-Test/Idle, and high while the TAP is parked there
(CHK-BSR-RTI).
"""

from __future__ import annotations

from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_types import DtpJtagInstr, DtpScanCtrlExpect

from .dtp_jtag_ac_extest_train_test_seq import RTI_CHECK_ID, RTI_SIGNAL
from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_ac_extest_pulse_test_seq(dtp_jtag_base_test_seq):
    """Run EXTEST_PULSE scan-loopback, run_test_idle strobe, and scan-control checks."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BSR-LOOPBACK",
                "CHK-BSR-SELECT",
                "CHK-BSR-SCAN-CTRL",
                "CHK-BSR-RTI",
                "CHK-BYPASS-DELAY",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        rng = self.rng("ac_extest_pulse")
        await self.reset_to_tlr()
        self.log_step(1, "EXTEST_TRAIN preload through the looped-back chain")
        await self.check_loopback_scan(DtpJtagInstr.EXTEST_TRAIN, 0x33)
        self.log_step(2, "EXTEST_PULSE loopback across directed, walking-one, and edge patterns")
        await self.check_loopback_patterns(DtpJtagInstr.EXTEST_PULSE)
        for pattern in (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            await self.check_loopback_scan(DtpJtagInstr.EXTEST_PULSE, pattern)
        for pattern in (0xAA, 0x55, 0xFF, 0x00):
            await self.check_loopback_scan(DtpJtagInstr.EXTEST_PULSE, pattern)
        self.log_step(3, "EXTEST_PULSE scan controls; run_test_idle pulses once, on the return")
        counts = await self.check_bsr_scan_ctrl(
            DtpJtagInstr.EXTEST_PULSE,
            self.random_pattern(DTP_BSR_MODEL_LEN, rng),
            extra_signals=(RTI_SIGNAL,),
        )
        self.family_check(
            RTI_CHECK_ID,
            f"{RTI_SIGNAL} pulses across the scan",
            counts[RTI_SIGNAL],
            1,
            context="EXTEST_PULSE DR scan",
        )
        self.log_step(4, "EXTEST_PULSE parked in Run-Test/Idle holds run_test_idle high")
        context = "EXTEST_PULSE parked in Run-Test/Idle"
        await self.check_scan_observable(RTI_CHECK_ID, RTI_SIGNAL, 1, context=context)
        await self.check_scan_observable(RTI_CHECK_ID, "jtag_bsr_select", 0, context=context)
        self.log_step(5, "BYPASS scan: select stays low while the TAP strobes pulse")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.BYPASS_3F, 0x3C3C, width=16, mode=DtpScanCtrlExpect.UNSELECTED
        )
        await self.finalize_family_checker()
