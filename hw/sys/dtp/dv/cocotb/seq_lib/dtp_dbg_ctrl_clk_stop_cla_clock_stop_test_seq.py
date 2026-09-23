# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_ctrl_clk_stop_cla_clock_stop_test."""

from __future__ import annotations

from env.dtp_dv_cfg import DTP_NUM_CLK_STOP_REQ

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq(dtp_debug_tdr_base_test_seq):
    """Check CLA clock-stop request aggregation and DEBUG_CONTROL readback."""

    async def body(self) -> None:
        self.log_banner("DEBUG_CONTROL CLA Clock Stop")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"}, use_monitor=False
        )

        self.log_step(1, "Reset TAP and clear clock-stop requests")
        await self.reset_to_tlr()
        await self.set_clk_stop_requests(0)

        reset_value = await self.read_debug_control()
        self.log_debug_control("After reset", reset_value)
        self.family_check("CHK-DBG-TDR", "DEBUG_CONTROL reset", reset_value, 0)

        self.log_step(2, "Set CLA_CLOCK_STOP_EN and check exported enable")
        control_value = self.pack_debug_control(cla_clock_stop_en=1)
        await self.write_debug_control(control_value)
        await self.wait_sys_cycles()
        await self.expect_dbg_signal("cla_clock_stop_en", 1, context="enable exported")
        await self.wait_for_signal_value("stop_clks", 0, context="no CLA request")

        self.log_step(3, "Drive CLA clock-stop requests and expect stop_clks")
        # Seeded per-pass nonzero request mask: any asserted CLA request must
        # stop the clocks, so repeated loops cover different aggregation inputs.
        request_mask = self.rng("cla_clk_stop_mask").randint(1, (1 << DTP_NUM_CLK_STOP_REQ) - 1)
        request_context = f"xtrig_clk_stop_req=0x{request_mask:03x}"
        await self.set_clk_stop_requests(request_mask)
        await self.wait_for_signal_value("stop_clks", 1, context=request_context)

        self.log_step(4, "Read DEBUG_CONTROL and expect CLA_CLOCK_STOP status")
        readback = await self.read_debug_control(shift_value=control_value)
        decoded = self.log_debug_control("CLA request readback", readback)
        self.check_debug_control_fields(
            decoded, {"cla_clock_stop": 1, "cla_clock_stop_en": 1}, context=request_context
        )

        self.log_step(5, "Clear CLA request and expect stop/readback to clear")
        await self.set_clk_stop_requests(0)
        await self.wait_for_signal_value("stop_clks", 0, context="xtrig_clk_stop_req=0")

        readback = await self.read_debug_control(shift_value=control_value)
        decoded = self.log_debug_control("CLA request cleared readback", readback)
        self.check_debug_control_fields(
            decoded, {"cla_clock_stop": 0}, context="xtrig_clk_stop_req=0"
        )

        self.log_step(6, "Clear CLA_CLOCK_STOP_EN")
        clear_value = self.pack_debug_control(cla_clock_stop_en=0)
        await self.write_debug_control(clear_value)
        await self.wait_sys_cycles()
        await self.expect_dbg_signal("cla_clock_stop_en", 0, context="enable cleared")
        self.log_summary(
            "CLA clock-stop complete",
            enabled_control=f"0x{control_value:02x}",
            final_control=f"0x{clear_value:02x}",
        )
        await self.finalize_family_checker()
