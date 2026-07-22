# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_clamp_release_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_clamp_release_test_seq(dtp_debug_tdr_base_test_seq):
    """Run CLAMP_RELEASE TMP persistence checks."""

    async def body(self) -> None:
        self.log_banner("CLAMP_RELEASE TMP persistence")

        self.log_step(1, "Reset TAP and confirm release is harmless without a prior hold")
        await self.reset_tap()
        await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
        released = await self.read_tmp_status()
        decoded = self.log_tmp_status("Initial CLAMP_RELEASE", released)
        self.assert_equal("TMP_STATUS.persistence", decoded["persistence"], 0, "initial release")

        patterns = self.directed_patterns(8, rng=self.rng("clamp_release"))
        self.log_step(2, "Loop through hold/release patterns")
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "SAMPLE_PRELOAD pattern=0x%02x", pattern)
            await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, pattern, 8)

            await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
            held = await self.read_tmp_status()
            decoded_held = self.log_tmp_status("After CLAMP_HOLD setup", held)
            self.assert_equal("TMP_STATUS.persistence", decoded_held["persistence"], 1, "hold setup")

            await self.load_ir(DtpJtagInstr.BYPASS_3F)
            held = await self.read_tmp_status()
            decoded_held = self.log_tmp_status("After BYPASS before release", held)
            self.assert_equal(
                "TMP_STATUS.persistence",
                decoded_held["persistence"],
                1,
                "pre-release switch",
            )

            await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
            await self.expect_decoded_instruction(DtpJtagInstr.CLAMP_RELEASE)
            released = await self.read_tmp_status()
            decoded_released = self.log_tmp_status("After CLAMP_RELEASE", released)
            self.assert_equal(
                "TMP_STATUS.persistence",
                decoded_released["persistence"],
                0,
                "release clear",
            )

        self.log_step(3, "Confirm repeated CLAMP_RELEASE keeps persistence clear")
        await self.load_ir(DtpJtagInstr.CLAMP_RELEASE)
        released = await self.read_tmp_status()
        decoded = self.log_tmp_status("Repeated CLAMP_RELEASE", released)
        self.assert_equal("TMP_STATUS.persistence", decoded["persistence"], 0, "repeated release")

        self.log_summary("CLAMP_RELEASE TMP persistence complete", patterns=len(patterns))
