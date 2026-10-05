# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_undef_instr_test.

Every reserved or undefined IR opcode decodes as itself and selects the one-bit
BYPASS path: its DR scan returns TDI one TCK late, raises none of the four
instruction-qualified host chain selects, and leaves the debug-TDR pin outputs
at their reset image.
"""

from __future__ import annotations

from env.dtp_types import UNDEFINED_BYPASS_INSTRS

from .dtp_debug_tdr_base_test_seq import DEBUG_OUTPUT_DEFAULTS, dtp_debug_tdr_base_test_seq
from .dtp_jtag_base_test_seq import NO_HOST_SELECT_CHECK_ID


class dtp_jtag_undef_instr_test_seq(dtp_debug_tdr_base_test_seq):
    """Run undefined-instruction fallback checks."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BYPASS-DELAY",
                NO_HOST_SELECT_CHECK_ID,
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        rng = self.rng("undef_instr")
        self.log_step(1, "Reset TAP")
        await self.reset_to_tlr()
        self.log_step(2, "Each reserved opcode decodes, scans the bypass, raises no host select")
        total = len(UNDEFINED_BYPASS_INSTRS)
        for idx, instr in enumerate(UNDEFINED_BYPASS_INSTRS, start=1):
            self.log_iteration(idx, total, "reserved opcode 0x%02x", int(instr))
            await self.check_bypass_no_host_select(instr, 0xA5A5_5A5A_C3C3_3C3C)
            await self.check_bypass_delay(instr, self.random_pattern(32, rng), width=32)
        self.log_step(3, "Debug-TDR pin outputs show the reset image")
        self.check_debug_outputs(
            NO_HOST_SELECT_CHECK_ID,
            await self.snapshot_debug_outputs(),
            DEBUG_OUTPUT_DEFAULTS,
            context="after every reserved-opcode scan",
        )
        self.log_step(4, "Seeded opcode sample: directed-pattern bypass sweep")
        sample_count = min(self.random_count, total)
        for instr in rng.sample(list(UNDEFINED_BYPASS_INSTRS), sample_count):
            await self.check_bypass_patterns(instr, width=32)
        await self.finalize_family_checker()
