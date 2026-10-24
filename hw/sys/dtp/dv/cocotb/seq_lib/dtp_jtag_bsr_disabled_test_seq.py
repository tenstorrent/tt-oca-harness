# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_bsr_disabled_test.

The DUT is elaborated with its boundary-scan instructions disabled
(``DTP_BSR_DISABLED``). JTAG_CAPS reports the four boundary-scan enables
clear, and SAMPLE/PRELOAD, EXTEST, EXTEST_TRAIN, EXTEST_PULSE, and INTEST
each behave as BYPASS at the boundary-scan host port and on TDO ("Boundary
Scan Support", PTAP document): the instruction decodes as itself, its DR scan
leaves the boundary-scan select low while the TAP's strobes pulse, and the
scan returns TDI one TCK late behind a leading 0. ``tb_top`` ties the
boundary-scan return to its output, so that return presents the same TDO as
the bypass register and only the select tells the two paths apart.
"""

from __future__ import annotations

from env.dtp_tap_device import DTP_BSR_MODEL_LEN, DTP_EXPECTED_JTAG_CAPS
from env.dtp_types import DtpJtagInstr, DtpScanCtrlExpect

from .dtp_debug_tdr_base_test_seq import CAPS_CHECK_ID, dtp_debug_tdr_base_test_seq

BSR_INSTRUCTIONS: tuple[DtpJtagInstr, ...] = (
    DtpJtagInstr.SAMPLE_PRELOAD,
    DtpJtagInstr.EXTEST,
    DtpJtagInstr.EXTEST_TRAIN,
    DtpJtagInstr.EXTEST_PULSE,
    DtpJtagInstr.INTEST,
)
# The boundary-scan enables, JTAG_CAPS bits 8 to 11, by their decode_jtag_caps names.
BSR_CAPS_FIELDS: tuple[str, ...] = ("bsr_en", "extest_train_en", "extest_pulse_en", "intest_en")
BSR_CAPS_MASK = 0xF << 8


class dtp_jtag_bsr_disabled_test_seq(dtp_debug_tdr_base_test_seq):
    """Check JTAG_CAPS and the BYPASS behavior of every boundary-scan instruction."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-CAPS",
                "CHK-IR-DECODE",
                "CHK-BSR-SELECT",
                "CHK-BSR-SCAN-CTRL",
                "CHK-BYPASS-DELAY",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        await self.reset_to_tlr()
        self.log_step(1, "JTAG_CAPS reports the boundary-scan enables clear")
        value = await self.read_caps_tdr("JTAG_CAPS")
        decoded = self.log_jtag_caps(value)
        self.family_check(
            CAPS_CHECK_ID,
            "JTAG_CAPS",
            value,
            DTP_EXPECTED_JTAG_CAPS & ~BSR_CAPS_MASK,
            context="packed value",
        )
        for name in BSR_CAPS_FIELDS:
            self.family_check(CAPS_CHECK_ID, f"JTAG_CAPS.{name}", decoded[name], 0)

        self.log_step(2, "Every boundary-scan instruction scans the one-bit bypass register")
        for idx, instr in enumerate(BSR_INSTRUCTIONS, start=1):
            self.log_iteration(idx, len(BSR_INSTRUCTIONS), "%s", instr.name)
            for pattern in self.directed_patterns(
                DTP_BSR_MODEL_LEN, rng=self.rng(f"bsr_disabled_{instr.name.lower()}")
            ):
                await self.check_bsr_scan_ctrl(instr, pattern, mode=DtpScanCtrlExpect.UNSELECTED)
        await self.finalize_family_checker()
