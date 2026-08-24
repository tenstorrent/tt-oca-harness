# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_undef_instr_test.

Checks that reserved/undefined IR opcodes select the one-bit BYPASS path.
"""

from __future__ import annotations

from env.dtp_types import UNDEFINED_BYPASS_INSTRS

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_undef_instr_test_seq(dtp_jtag_base_test_seq):
    """Run undefined-instruction fallback checks."""

    async def body(self) -> None:
        await self.reset_tap()
        rng = self.rng("undef_instr")
        for instr in UNDEFINED_BYPASS_INSTRS:
            self.log.info("Checking undefined opcode 0x%02x falls back to BYPASS", int(instr))
            await self.check_bypass_delay(instr, 0xA5A5_5A5A_C3C3_3C3C)
            await self.check_bypass_delay(instr, self.random_pattern(32, rng), width=32)

        sample_count = min(self.random_count, len(UNDEFINED_BYPASS_INSTRS))
        for instr in rng.sample(list(UNDEFINED_BYPASS_INSTRS), sample_count):
            await self.check_bypass_patterns(instr, width=32)
