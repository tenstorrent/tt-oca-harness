# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_tmp_status_register_smoke_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_tmp_status_register_smoke_test_seq(dtp_debug_tdr_base_test_seq):
    """Check TMP_STATUS reset readback and persistence tracking."""

    async def body(self) -> None:
        self.log_banner("TMP_STATUS Register Smoke")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-TMP-PERSIST", "CHK-DBG-TDR"}, use_monitor=False
        )

        self.log_step(1, "Reset TAP and confirm TMP starts Persistence-Off")
        await self.reset_to_tlr()
        await self.check_tmp_persistence("After reset", 0)

        self.log_step(2, "Read TMP_STATUS with several DR shift values")
        # Exhaustive 2-bit sweep in a seeded per-pass order: repeated loops
        # exercise different arm/clear interleavings of bypass_escape.
        shift_values = [0x0, 0x1, 0x2, 0x3]
        self.rng("tmp_smoke_shift_order").shuffle(shift_values)
        for idx, shift_value in enumerate(shift_values, start=1):
            # Bit 1 is read-only persistence status, so it must remain 0 until
            # CLAMP_HOLD drives the TMP controller into Persistence-On.
            await self.check_tmp_persistence(
                f"Shift-value sweep {idx}",
                0,
                shift_value=shift_value,
                context=f"shift_value=0b{shift_value:02b}",
            )

        self.log_step(3, "Apply CLAMP_HOLD and expect Persistence-On")
        await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
        held = await self.check_tmp_persistence("After CLAMP_HOLD", 1)

        self.log_step(4, "Read IDCODE to prove TMP_STATUS access did not disturb routing")
        idcode = await self.check_idcode_marker(context="after TMP_STATUS")

        self.log_summary(
            "TMP_STATUS smoke complete",
            final_tmp_status=f"0b{held:02b}",
            idcode=f"0x{idcode:08x}",
        )
        await self.finalize_family_checker()
