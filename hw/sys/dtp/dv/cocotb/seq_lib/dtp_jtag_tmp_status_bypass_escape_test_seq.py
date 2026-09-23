# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_tmp_status_bypass_escape_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_tmp_status_bypass_escape_test_seq(dtp_debug_tdr_base_test_seq):
    """Check TMP BYPASS_ESCAPE exits persistence mode."""

    async def body(self) -> None:
        self.log_banner("TMP_STATUS BYPASS_ESCAPE")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-TMP-PERSIST", "CHK-TMP-ESCAPE", "CHK-BYPASS-DELAY"},
            use_monitor=False,
        )

        self.log_step(1, "Reset TAP and establish Persistence-On through CLAMP_HOLD")
        await self.reset_to_tlr()
        await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
        held = await self.check_tmp_persistence("After CLAMP_HOLD", 1)

        self.log_step(2, "Arm BYPASS_ESCAPE and verify bit 0 is retained")
        await self.write_tmp_status(0x1)
        for idx, shift_value in enumerate([0x1, 0x3], start=1):
            self.log_iteration(
                idx, 2, "Read armed TMP_STATUS with shift_value=0b%s", format(shift_value, "02b")
            )
            await self.check_tmp_escape(
                "Armed readback",
                1,
                shift_value=shift_value,
                context=f"shift_value=0b{shift_value:02b}",
            )

        self.log_step(3, "Select BYPASS twice to trigger the escape transition")
        # The TMP controller samples `bypass_selected` during Update-IR. Load
        # BYPASS twice so the second Update-IR observes BYPASS already selected.
        await self.load_ir(DtpJtagInstr.BYPASS_3F)
        await self.load_ir(DtpJtagInstr.BYPASS_3F)

        self.log_step(4, "Verify Persistence-Off after BYPASS escape")
        released = await self.check_tmp_persistence("After BYPASS escape", 0)

        self.log_step(5, "Check normal BYPASS scan routing after escape")
        # Seeded per-pass pattern: repeated loops shift different data through
        # the recovered BYPASS path instead of one constant.
        bypass_pattern = self.rng("tmp_bypass_escape").getrandbits(16)
        await self.check_bypass_delay(DtpJtagInstr.BYPASS_3F, bypass_pattern, width=16)
        self.log_summary(
            "TMP BYPASS_ESCAPE complete",
            held=f"0b{held:02b}",
            released=f"0b{released:02b}",
            bypass_pattern=f"0x{bypass_pattern:04x}",
        )
        await self.finalize_family_checker()
