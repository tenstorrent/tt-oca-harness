# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test."""

from __future__ import annotations

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq(dtp_debug_tdr_base_test_seq):
    """Check JTAG_CLOCK_STOP drives and releases stop_clks_o."""

    async def body(self) -> None:
        self.log_banner("DEBUG_CONTROL JTAG Clock Stop")

        self.log_step(1, "Reset TAP and clear CLA clock-stop requests")
        await self.reset_tap()
        await self.set_clk_stop_requests(0)

        reset_value = await self.read_debug_control()
        self.log_debug_control("After reset", reset_value)
        self.assert_equal("DEBUG_CONTROL reset", reset_value, 0)

        self.log_step(2, "Set JTAG_CLOCK_STOP and expect stop_clks to assert")
        control_value = self.pack_debug_control(jtag_clock_stop=1)
        await self.write_debug_control(control_value)
        await self.wait_sys_cycles()
        await self.wait_for_signal_value("stop_clks", 1, context="jtag_clock_stop=1")
        await self.expect_signal("cla_clock_stop_en", 0)

        self.log_step(3, "Read DEBUG_CONTROL and confirm CLA status ignores JTAG stop")
        readback = await self.read_debug_control(shift_value=control_value)
        decoded = self.log_debug_control("JTAG stop readback", readback)
        self.assert_equal("DEBUG_CONTROL.jtag_clock_stop", decoded["jtag_clock_stop"], 1)
        self.assert_equal("DEBUG_CONTROL.cla_clock_stop", decoded["cla_clock_stop"], 0)

        self.log_step(4, "Clear JTAG_CLOCK_STOP and expect stop_clks to release")
        clear_value = self.pack_debug_control(jtag_clock_stop=0)
        await self.write_debug_control(clear_value)
        await self.wait_sys_cycles()
        await self.wait_for_signal_value("stop_clks", 0, context="jtag_clock_stop=0")

        self.log_step(5, "Repeat seeded stop/release toggles to prove no one-shot behavior")
        # Seeded per-pass toggle count and settle spacing: each loop stresses
        # a different assert/release cadence of the same control bit.
        rng = self.rng("jtag_clock_stop_toggles")
        toggles = rng.randint(1, 4)
        for toggle in range(1, toggles + 1):
            await self.write_debug_control(self.pack_debug_control(jtag_clock_stop=1))
            await self.wait_sys_cycles(rng.randint(2, 8))
            await self.wait_for_signal_value("stop_clks", 1, context=f"toggle#{toggle}.stop")
            await self.write_debug_control(clear_value)
            await self.wait_sys_cycles(rng.randint(2, 8))
            await self.wait_for_signal_value("stop_clks", 0, context=f"toggle#{toggle}.release")

        final_readback = await self.read_debug_control(shift_value=clear_value)
        self.log_debug_control("After JTAG stop clear", final_readback)
        self.log_summary(
            "JTAG clock-stop complete",
            asserted_control=f"0x{control_value:02x}",
            final_control=f"0x{final_readback:02x}",
        )
