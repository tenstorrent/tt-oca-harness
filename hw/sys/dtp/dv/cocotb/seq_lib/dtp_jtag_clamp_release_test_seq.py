# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_clamp_release_test.

Like CLAMP_HOLD, CLAMP_RELEASE scans the one-bit bypass register
(``CHK-BYPASS-DELAY``); the 2-bit register is TMP_STATUS. The looped-back
pattern is also the one-bit bypass register's TDO, so SAMPLE/PRELOAD shows it
selects the chain by the chain's select, high across each DR scan before a
hold and after the release (``CHK-BSR-SELECT``).
"""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_clamp_release_test_seq(dtp_debug_tdr_base_test_seq):
    """Run CLAMP_RELEASE TMP persistence checks."""

    async def body(self) -> None:
        self.log_banner("CLAMP_RELEASE TMP persistence")
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BSR-LOOPBACK",
                "CHK-BSR-SELECT",
                "CHK-BSR-SCAN-CTRL",
                "CHK-BYPASS-DELAY",
                "CHK-TMP-PERSIST",
            },
        )

        self.log_step(1, "Reset TAP and confirm release is harmless without a prior hold")
        await self.reset_to_tlr()
        await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
        released = await self.read_tmp_status()
        decoded = self.log_tmp_status("Initial CLAMP_RELEASE", released)
        self.family_check(
            "CHK-TMP-PERSIST",
            "TMP_STATUS.persistence",
            decoded["persistence"],
            0,
            context="initial release",
        )

        rng = self.rng("clamp_release")
        patterns = self.directed_patterns(8, rng=rng)
        self.log_step(2, "Loop through hold/release patterns")
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "SAMPLE_PRELOAD pattern=0x%02x", pattern)
            await self.check_bsr_scan_ctrl(DtpJtagInstr.SAMPLE_PRELOAD, pattern, 8)

            await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
            held = await self.read_tmp_status()
            decoded_held = self.log_tmp_status("After CLAMP_HOLD setup", held)
            self.family_check(
                "CHK-TMP-PERSIST",
                "TMP_STATUS.persistence",
                decoded_held["persistence"],
                1,
                context="hold setup",
            )

            await self.load_ir(DtpJtagInstr.BYPASS_3F)
            held = await self.read_tmp_status()
            decoded_held = self.log_tmp_status("After BYPASS before release", held)
            self.family_check(
                "CHK-TMP-PERSIST",
                "TMP_STATUS.persistence",
                decoded_held["persistence"],
                1,
                context="pre-release switch",
            )

            await self.check_bypass_delay(DtpJtagInstr.CLAMP_RELEASE, self.random_pattern(64, rng))
            released = await self.read_tmp_status()
            decoded_released = self.log_tmp_status("After CLAMP_RELEASE", released)
            self.family_check(
                "CHK-TMP-PERSIST",
                "TMP_STATUS.persistence",
                decoded_released["persistence"],
                0,
                context="release clear",
            )

        self.log_step(3, "Confirm repeated CLAMP_RELEASE keeps persistence clear")
        await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
        released = await self.read_tmp_status()
        decoded = self.log_tmp_status("Repeated CLAMP_RELEASE", released)
        self.family_check(
            "CHK-TMP-PERSIST",
            "TMP_STATUS.persistence",
            decoded["persistence"],
            0,
            context="repeated release",
        )

        self.log_step(
            4, "SAMPLE/PRELOAD after the release selects the chain and loops the pattern back"
        )
        await self.check_bsr_scan_ctrl(DtpJtagInstr.SAMPLE_PRELOAD, patterns[-1], 8)

        self.log_summary("CLAMP_RELEASE TMP persistence complete", patterns=len(patterns))
        await self.finalize_family_checker()
