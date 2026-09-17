# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_clamp_hold_test.

CLAMP_HOLD (IR 0x0A) is a TMP instruction: its Update-IR turns test-mode
persistence on, its data register is the one-bit bypass, and TMP_STATUS bit 1
reads the persistence back. Persistence survives an instruction switch to
BYPASS, CLAMP_RELEASE clears it, and a TAP reset leaves it clear.
"""

from __future__ import annotations

import random

from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_clamp_hold_test_seq(dtp_debug_tdr_base_test_seq):
    """Run CLAMP_HOLD bypass-path and TMP persistence checks."""

    async def check_persistence(self, label: str, expected: int) -> None:
        """Read TMP_STATUS and record its persistence bit."""
        status = await self.read_tmp_status()
        decoded = self.log_tmp_status(f"After {label}", status)
        self.family_check(
            "CHK-TMP-PERSIST",
            "TMP_STATUS.persistence",
            decoded["persistence"],
            expected,
            context=label,
        )

    async def check_clamp_hold_cycle(self, pattern: int, rng: random.Random) -> None:
        """Preload, then CLAMP_HOLD sets persistence, BYPASS keeps it, CLAMP_RELEASE clears it."""
        await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, pattern, 8)
        await self.check_bypass_delay(DtpJtagInstr.CLAMP_HOLD, self.random_pattern(64, rng))
        await self.check_persistence("CLAMP_HOLD", 1)
        await self.load_ir(DtpJtagInstr.BYPASS_3F)
        await self.check_persistence("BYPASS instruction switch", 1)
        await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
        await self.check_persistence("CLAMP_RELEASE", 0)

    async def body(self) -> None:
        self.log_banner("CLAMP_HOLD TMP persistence")
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BSR-LOOPBACK",
                "CHK-BYPASS-DELAY",
                "CHK-TMP-PERSIST",
            },
            # TMP_STATUS reads go through driver-level TDR ops the sequence
            # cannot count, so the pin-level scan monitor stays off.
            use_monitor=False,
        )

        self.log_step(1, "Reset TAP before CLAMP_HOLD sweep")
        await self.reset_to_tlr()

        rng = self.rng("clamp_hold")
        patterns = self.directed_patterns(8, rng=rng)
        self.log_step(2, "Loop through scan patterns and verify TMP persistence")
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "SAMPLE_PRELOAD pattern=0x%02x", pattern)
            await self.check_clamp_hold_cycle(pattern, rng)

        self.log_step(3, "Confirm TAP reset leaves TMP persistence clear")
        await self.reset_to_tlr()
        await self.check_persistence("TAP reset", 0)

        self.log_summary("CLAMP_HOLD TMP persistence complete", patterns=len(patterns))
        await self.finalize_family_checker()
