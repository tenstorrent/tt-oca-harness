# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_clamp_hold_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_clamp_hold_test_seq(dtp_debug_tdr_base_test_seq):
    """Run CLAMP_HOLD TMP persistence checks."""

    async def body(self) -> None:
        self.log_banner("CLAMP_HOLD TMP persistence")

        self.log_step(1, "Reset TAP before CLAMP_HOLD sweep")
        await self.reset_tap()

        patterns = self.directed_patterns(8, rng=self.rng("clamp_hold"))
        self.log_step(2, "Loop through scan patterns and verify TMP persistence")
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "SAMPLE_PRELOAD pattern=0x%02x", pattern)
            await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, pattern, 8)

            await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
            await self.expect_decoded_instruction(DtpJtagInstr.CLAMP_HOLD)
            status = await self.read_tmp_status()
            decoded = self.log_tmp_status("After CLAMP_HOLD", status)
            self.assert_equal("TMP_STATUS.persistence", decoded["persistence"], 1, "CLAMP_HOLD")

            await self.load_ir(DtpJtagInstr.BYPASS_3F)
            status = await self.read_tmp_status()
            decoded = self.log_tmp_status("After BYPASS instruction switch", status)
            self.assert_equal(
                "TMP_STATUS.persistence",
                decoded["persistence"],
                1,
                "instruction switch",
            )

            await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
            status = await self.read_tmp_status()
            decoded = self.log_tmp_status("After CLAMP_RELEASE", status)
            self.assert_equal("TMP_STATUS.persistence", decoded["persistence"], 0, "CLAMP_RELEASE")

        self.log_step(3, "Confirm TAP reset leaves TMP persistence clear")
        await self.reset_tap()
        status = await self.read_tmp_status()
        decoded = self.log_tmp_status("After TAP reset", status)
        self.assert_equal("TMP_STATUS.persistence", decoded["persistence"], 0, "TAP reset")

        self.log_summary("CLAMP_HOLD TMP persistence complete", patterns=len(patterns))
