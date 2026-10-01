# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_clamp_hold_test.

CLAMP_HOLD (IR 0x0A) is a TMP instruction: its Update-IR turns test-mode
persistence on, its data register is the one-bit bypass, and TMP_STATUS bit 1
reads the persistence back. Persistence is off before CLAMP_HOLD, survives an
instruction switch to BYPASS and five TMS-high clocks into Test-Logic-Reset,
and CLAMP_RELEASE or a TRST reset clears it.
"""

from __future__ import annotations

import random

from env.dtp_types import DtpJtagInstr, DtpTapState
from ocah_jtag_vip import TLR_TMS_ONES

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
        await self.check_persistence("before CLAMP_HOLD", 0)
        await self.check_bypass_delay(DtpJtagInstr.CLAMP_HOLD, self.random_pattern(64, rng))
        await self.check_persistence("CLAMP_HOLD", 1)
        await self.load_ir(DtpJtagInstr.BYPASS_3F)
        await self.check_persistence("BYPASS instruction switch", 1)
        await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
        await self.check_persistence("CLAMP_RELEASE", 0)

    async def body(self) -> None:
        self.log_banner("CLAMP_HOLD TMP persistence")
        checker = await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BSR-LOOPBACK",
                "CHK-BYPASS-DELAY",
                "CHK-TMP-PERSIST",
            },
        )

        self.log_step(1, "Reset TAP before CLAMP_HOLD sweep")
        await self.reset_to_tlr()

        rng = self.rng("clamp_hold")
        patterns = self.directed_patterns(8, rng=rng)
        self.log_step(2, "Loop through scan patterns and verify TMP persistence")
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "SAMPLE_PRELOAD pattern=0x%02x", pattern)
            await self.check_clamp_hold_cycle(pattern, rng)

        self.log_step(
            3, "Persistence survives a TMS-driven Test-Logic-Reset; a TRST reset clears it"
        )
        await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
        await self.check_persistence("CLAMP_HOLD before Test-Logic-Reset", 1)
        for _ in range(TLR_TMS_ONES):
            await self.tms_expect(1)
        item = await self.sample_observables()
        checker.check_tms_ones_to_tlr(TLR_TMS_ONES, item.result, context="persistence on")
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)
        await self.check_persistence("after five TMS-high clocks", 1)
        await self.reset_to_tlr()
        await self.check_persistence("TRST from Persistence-On", 0)

        self.log_summary("CLAMP_HOLD TMP persistence complete", patterns=len(patterns))
        await self.finalize_family_checker()
