# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_jtag_caps_test."""

from __future__ import annotations

from env.dtp_tap_device import DTP_JTAG_CAPS_LEN
from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import EXPECTED_CAPS_BY_REG, dtp_debug_tdr_base_test_seq


class dtp_dbg_jtag_caps_test_seq(dtp_debug_tdr_base_test_seq):
    """Check the 60-bit JTAG_CAPS TDR."""

    async def body(self) -> None:
        self.log_banner("JTAG_CAPS")

        self.log_step(1, "Reset TAP and read JTAG_CAPS")
        await self.reset_tap()

        value = await self.read_caps_tdr("JTAG_CAPS")
        decoded = self.log_jtag_caps(value)
        self.expect_caps_value("JTAG_CAPS", value)

        self.log_step(2, "Verify every decoded JTAG_CAPS field")
        expected_fields = self.decode_jtag_caps(EXPECTED_CAPS_BY_REG["JTAG_CAPS"])
        for name, observed in decoded.items():
            self.assert_equal(f"JTAG_CAPS.{name}", observed, expected_fields[name])

        self.log_step(3, "Check multiple reads are stable")
        self.assert_equal(
            "JTAG_CAPS multi-read value", await self.check_caps_multi_read("JTAG_CAPS"), value
        )

        self.log_step(4, "Check read-only behavior with directed and random patterns")
        self.assert_equal(
            "JTAG_CAPS read-only sweep",
            await self.check_caps_read_only_patterns("JTAG_CAPS", DTP_JTAG_CAPS_LEN),
            value,
        )

        self.log_step(5, "Switch through other instructions and read JTAG_CAPS again")
        for idx, instr in enumerate([DtpJtagInstr.IDCODE, DtpJtagInstr.BYPASS_3F], start=1):
            self.log_iteration(idx, 2, "load %s before re-reading JTAG_CAPS", instr.name)
            await self.load_ir(instr)
            reread = await self.read_caps_tdr("JTAG_CAPS")
            self.assert_equal(
                "JTAG_CAPS after instruction switch",
                reread,
                value,
                context=instr.name,
            )

        self.log_summary("JTAG_CAPS complete", value=f"0x{value:015x}")
