# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_tmp_status_chrst_n_in_persistence_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr
from ocah_jtag_vip import OcahJtagState

from .dtp_debug_tdr_base_test_seq import TMP_CHRST_CHECK_ID, dtp_debug_tdr_base_test_seq


class dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq(dtp_debug_tdr_base_test_seq):
    """Check TMP persistence across the system reset and Test-Logic-Reset.

    Persistence set by CLAMP_HOLD survives an ``rst_n_i`` pulse and a
    TMS-driven Test-Logic-Reset, which leaves the boundary-scan host
    control's ``chrst_n`` released; once CLAMP_RELEASE ends persistence,
    Test-Logic-Reset asserts ``chrst_n``.
    """

    async def check_chrst_n_in_tlr(self, expected: int, *, context: str) -> None:
        """Walk to Test-Logic-Reset without TRST and record ``chrst_n`` there."""
        await self.reset_tap_by_tms()
        await self.check_scan_observable(
            TMP_CHRST_CHECK_ID, "jtag_bsr_test_logic_reset", 1, context=context
        )
        await self.check_scan_observable(
            TMP_CHRST_CHECK_ID, "jtag_bsr_chrst_n", expected, context=context
        )
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

    async def body(self) -> None:
        self.log_banner("TMP_STATUS CHRST_N Persistence")
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-TMP-PERSIST",
                "CHK-TMP-CHRST",
                "CHK-DBG-TDR",
                "CHK-RESET-COUNT",
            },
        )

        self.log_step(1, "Reset TAP and enter TMP Persistence-On with CLAMP_HOLD")
        await self.reset_to_tlr()
        await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
        before = await self.check_tmp_persistence("Before system reset", 1)

        self.log_step(2, "Pulse the system reset rst_n_i while keeping TAP accessible")
        # Seeded per-pass pulse width in clk_i cycles; TCK is idle during the
        # pulse.
        reset_cycles = self.rng("tmp_chrst_pulse").randint(3, 12)
        await self.pulse_system_reset(cycles=reset_cycles)

        self.log_step(3, "Confirm Persistence-On survives the system reset pulse")
        after = await self.check_tmp_persistence(
            "After system reset",
            1,
            context=f"before=0b{before:02b} reset_cycles={reset_cycles}",
        )

        self.log_step(4, "Walk Test-Logic-Reset with persistence on: chrst_n stays released")
        await self.check_chrst_n_in_tlr(1, context="persistence on")
        await self.check_tmp_persistence("After TMS Test-Logic-Reset", 1)

        self.log_step(5, "Release persistence: Test-Logic-Reset asserts chrst_n")
        await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
        await self.check_tmp_persistence("After CLAMP_RELEASE", 0)
        await self.check_chrst_n_in_tlr(0, context="persistence off")
        await self.check_scan_observable(
            TMP_CHRST_CHECK_ID, "jtag_bsr_chrst_n", 1, context="Run-Test/Idle"
        )

        self.log_step(6, "Read IDCODE and expect the configured IDCODE")
        idcode = await self.check_idcode_value(context="after system reset and TLR")

        self.log_summary(
            "TMP persistence across the system reset and Test-Logic-Reset complete",
            before=f"0b{before:02b}",
            after=f"0b{after:02b}",
            idcode=f"0x{idcode:08x}",
        )
        await self.finalize_family_checker()
