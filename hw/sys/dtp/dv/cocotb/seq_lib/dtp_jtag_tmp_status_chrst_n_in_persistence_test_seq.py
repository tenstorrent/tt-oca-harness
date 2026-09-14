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

        self.log_step(1, "Reset TAP and enter TMP Persistence-On with CLAMP_HOLD")
        await self.reset_tap()
        await self.load_ir(DtpJtagInstr.CLAMP_HOLD)

        before = await self.read_tmp_status()
        decoded_before = self.log_tmp_status("Before chip reset", before)
        self.assert_equal(
            "TMP_STATUS.persistence before chip reset",
            decoded_before["persistence"],
            1,
        )

        self.log_step(2, "Pulse chip reset while keeping TAP accessible")
        # Seeded per-pass pulse width: repeated loops vary how long rst_n_i
        # stays low relative to the free-running TCK.
        reset_cycles = self.rng("tmp_chrst_pulse").randint(3, 12)
        await self.pulse_system_reset(cycles=reset_cycles)

        self.log_step(3, "Confirm Persistence-On survives the chip reset pulse")
        after = await self.read_tmp_status()
        decoded_after = self.log_tmp_status("After chip reset", after)
        self.assert_equal(
            "TMP_STATUS.persistence after chip reset",
            decoded_after["persistence"],
            1,
            context=f"before=0b{before:02b} after=0b{after:02b}",
        )

        self.log_step(4, "Check TAP still reads IDCODE after chip reset")
        idcode = await self.read_idcode()
        self.assert_equal(
            "IDCODE LSB after chip reset",
            idcode.result & 0x1,
            1,
            context=f"idcode=0x{idcode.result:08x}",
        )

        self.log_summary(
            "TMP persistence across chip reset complete",
            before=f"0b{before:02b}",
            after=f"0b{after:02b}",
            idcode=f"0x{idcode.result:08x}",
        )
