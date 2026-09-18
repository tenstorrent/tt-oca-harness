# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_tmp_status_chrst_n_in_persistence_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq(dtp_debug_tdr_base_test_seq):
    """Check that TMP persistence survives chip reset while TAP stays accessible."""

    async def body(self) -> None:
        self.log_banner("TMP_STATUS CHRST_N Persistence")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-TMP-PERSIST", "CHK-DBG-TDR"}, use_monitor=False
        )

        self.log_step(1, "Reset TAP and enter TMP Persistence-On with CLAMP_HOLD")
        await self.reset_to_tlr()
        await self.load_ir(DtpJtagInstr.CLAMP_HOLD)
        before = await self.check_tmp_persistence("Before chip reset", 1)

        self.log_step(2, "Pulse chip reset while keeping TAP accessible")
        # Seeded per-pass pulse width: repeated loops vary how long rst_n_i
        # stays low relative to the free-running TCK.
        reset_cycles = self.rng("tmp_chrst_pulse").randint(3, 12)
        await self.pulse_system_reset(cycles=reset_cycles)

        self.log_step(3, "Confirm Persistence-On survives the chip reset pulse")
        after = await self.check_tmp_persistence(
            "After chip reset",
            1,
            context=f"before=0b{before:02b} reset_cycles={reset_cycles}",
        )

        self.log_step(4, "Check TAP still reads IDCODE after chip reset")
        idcode = await self.check_idcode_marker(context="after chip reset")

        self.log_summary(
            "TMP persistence across chip reset complete",
            before=f"0b{before:02b}",
            after=f"0b{after:02b}",
            idcode=f"0x{idcode:08x}",
        )
        await self.finalize_family_checker()
