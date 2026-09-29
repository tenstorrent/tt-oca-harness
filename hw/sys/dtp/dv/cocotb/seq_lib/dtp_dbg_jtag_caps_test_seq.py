# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_jtag_caps_test."""

from __future__ import annotations

from env.dtp_tap_device import DTP_JTAG_CAPS_LEN

from .dtp_debug_tdr_base_test_seq import EXPECTED_CAPS_BY_REG, dtp_debug_tdr_base_test_seq


class dtp_dbg_jtag_caps_test_seq(dtp_debug_tdr_base_test_seq):
    """Check the 60-bit JTAG_CAPS TDR."""

    async def body(self) -> None:
        self.log_banner("JTAG_CAPS")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-CAPS", "CHK-CAPS-RO"}, use_monitor=False
        )

        self.log_step(1, "Reset TAP and read JTAG_CAPS")
        await self.reset_to_tlr()

        value = await self.read_caps_tdr("JTAG_CAPS")
        decoded = self.log_jtag_caps(value)
        self.expect_caps_value("JTAG_CAPS", value)

        self.log_step(2, "Verify every decoded JTAG_CAPS field")
        expected_fields = self.decode_jtag_caps(EXPECTED_CAPS_BY_REG["JTAG_CAPS"])
        for name, observed in decoded.items():
            self.family_check("CHK-CAPS", f"JTAG_CAPS.{name}", observed, expected_fields[name])

        self.log_step(3, "Check multiple reads are stable")
        self.family_check(
            "CHK-CAPS",
            "JTAG_CAPS multi-read value",
            await self.check_caps_multi_read("JTAG_CAPS"),
            value,
        )

        self.log_step(4, "Check read-only behavior with directed and random patterns")
        self.family_check(
            "CHK-CAPS",
            "JTAG_CAPS read-only sweep",
            await self.check_caps_read_only_patterns("JTAG_CAPS", DTP_JTAG_CAPS_LEN),
            value,
        )

        self.log_step(5, "Switch through other instructions and read JTAG_CAPS again")
        await self.check_caps_after_instruction_switch("JTAG_CAPS", value)

        self.log_summary("JTAG_CAPS complete", value=f"0x{value:015x}")
        await self.finalize_family_checker()
