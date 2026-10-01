# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_ac_extest_train_test.

EXTEST_TRAIN (IR 0x05) selects the boundary-scan chain, which this bench loops
back without boundary cells. The chain's ``run_test_idle`` strobe is the
Run-Test/Idle decode the AC training launches on: it is high while the TAP is
parked in Run-Test/Idle, low in Test-Logic-Reset, and low across a DR scan
until the scan returns to Run-Test/Idle.
"""

from __future__ import annotations

from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_types import DtpJtagInstr, DtpScanCtrlExpect, DtpTapState

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq

RTI_CHECK_ID = "CHK-BSR-RTI"
RTI_SIGNAL = "jtag_bsr_run_test_idle"
TLR_SIGNAL = "jtag_bsr_test_logic_reset"


class dtp_jtag_ac_extest_train_test_seq(dtp_jtag_base_test_seq):
    """Run EXTEST_TRAIN scan-loopback, run_test_idle strobe, and scan-control checks."""

    async def check_run_test_idle_strobe(self) -> None:
        """EXTEST_TRAIN parked in Run-Test/Idle raises run_test_idle; Test-Logic-Reset drops it."""
        await self.load_ir(DtpJtagInstr.EXTEST_TRAIN)
        await self.expect_decoded_instruction(DtpJtagInstr.EXTEST_TRAIN)
        context = "EXTEST_TRAIN parked in Run-Test/Idle"
        await self.check_scan_observable(RTI_CHECK_ID, RTI_SIGNAL, 1, context=context)
        await self.check_scan_observable(RTI_CHECK_ID, TLR_SIGNAL, 0, context=context)
        await self.check_scan_observable(RTI_CHECK_ID, "jtag_bsr_select", 0, context=context)
        await self.goto_tap_state(DtpTapState.TEST_LOGIC_RESET)
        context = "parked in Test-Logic-Reset"
        await self.check_scan_observable(RTI_CHECK_ID, RTI_SIGNAL, 0, context=context)
        await self.check_scan_observable(RTI_CHECK_ID, TLR_SIGNAL, 1, context=context)
        await self.goto_tap_state(DtpTapState.RUN_TEST_IDLE)

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
        rng = self.rng("ac_extest_train")
        await self.reset_to_tlr()
        self.log_step(1, "SAMPLE/PRELOAD zero preload through the looped-back chain")
        await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, 0x00)
        self.log_step(2, "EXTEST_TRAIN loopback across directed, train, and seeded patterns")
        await self.check_loopback_patterns(DtpJtagInstr.EXTEST_TRAIN)
        for pattern in (0x0F, 0xF0, 0x33, 0xCC):
            await self.check_loopback_scan(DtpJtagInstr.EXTEST_TRAIN, pattern)
        self.log_step(3, "run_test_idle strobe follows the TAP parking state")
        await self.check_run_test_idle_strobe()
        self.log_step(4, "EXTEST_TRAIN scan controls; run_test_idle high only on the return")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.EXTEST_TRAIN,
            self.random_pattern(DTP_BSR_MODEL_LEN, rng),
            extra_signals=(RTI_SIGNAL,),
        )
        self.check_run_test_idle_window(RTI_CHECK_ID, RTI_SIGNAL, context="EXTEST_TRAIN DR scan")
        self.log_step(5, "BYPASS scan: select stays low while the TAP strobes pulse")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.BYPASS_3F, 0x3C3C, width=16, mode=DtpScanCtrlExpect.UNSELECTED
        )
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0xA5)
        await self.finalize_family_checker()
