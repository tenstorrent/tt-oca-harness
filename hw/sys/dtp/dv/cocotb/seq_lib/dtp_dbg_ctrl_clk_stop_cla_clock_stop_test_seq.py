# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_ctrl_clk_stop_cla_clock_stop_test."""

from __future__ import annotations

from env.dtp_dv_cfg import DTP_NUM_CLK_STOP_REQ

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq(dtp_debug_tdr_base_test_seq):
    """Check CLA clock-stop request aggregation and DEBUG_CONTROL readback.

    A CLA request stops the clocks with CLA_CLOCK_STOP_EN set and with it
    clear. CLA_CLOCK_STOP reads the request OR alone: 0 under JTAG_CLOCK_STOP
    with no request, 1 once a request joins it, and 0 again when the request
    clears while JTAG_CLOCK_STOP keeps ``stop_clks`` asserted.
    """

    async def body(self) -> None:
        self.log_banner("DEBUG_CONTROL CLA Clock Stop")
        await self.attach_family_checker(
            {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN", "CHK-DBG-STOP-EDGE"},
        )
        _, off_edge_start = self.stop_clks_counts()
        full_mask = (1 << DTP_NUM_CLK_STOP_REQ) - 1

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

        self.log_step(3, "Drive request line 0, then a seeded mask; expect stop and status")
        # Seeded per-pass nonzero request mask: any asserted CLA request must
        # stop the clocks, so repeated loops cover different aggregation inputs.
        request_masks = (0x001, self.rng("cla_clk_stop_mask").randint(1, full_mask))
        for idx, request_mask in enumerate(request_masks, start=1):
            self.log_iteration(idx, len(request_masks), "xtrig_clk_stop_req=0x%03x", request_mask)
            request_context = f"xtrig_clk_stop_req=0x{request_mask:03x}"
            await self.set_clk_stop_requests(request_mask)
            await self.wait_for_signal_value("stop_clks", 1, context=request_context)

            readback = await self.read_debug_control(shift_value=control_value)
            decoded = self.log_debug_control("CLA request readback", readback)
            self.check_debug_control_fields(
                decoded, {"cla_clock_stop": 1, "cla_clock_stop_en": 1}, context=request_context
            )

            await self.set_clk_stop_requests(0)
            await self.wait_for_signal_value("stop_clks", 0, context="xtrig_clk_stop_req=0")

            readback = await self.read_debug_control(shift_value=control_value)
            decoded = self.log_debug_control("CLA request cleared readback", readback)
            self.check_debug_control_fields(
                decoded, {"cla_clock_stop": 0}, context="xtrig_clk_stop_req=0"
            )

        self.log_step(4, "Clear CLA_CLOCK_STOP_EN")
        clear_value = self.pack_debug_control(cla_clock_stop_en=0)
        await self.write_debug_control(clear_value)
        await self.wait_sys_cycles()
        await self.expect_dbg_signal("cla_clock_stop_en", 0, context="enable cleared")

        self.log_step(5, "Drive a seeded CLA request with CLA_CLOCK_STOP_EN clear")
        en_off_mask = self.rng("cla_clk_stop_mask_en_off").randint(1, full_mask)
        en_off_context = f"cla_clock_stop_en=0 xtrig_clk_stop_req=0x{en_off_mask:03x}"
        await self.set_clk_stop_requests(en_off_mask)
        await self.wait_for_signal_value("stop_clks", 1, context=en_off_context)
        await self.expect_dbg_signal("cla_clock_stop_en", 0, context=en_off_context)
        readback = await self.read_debug_control(shift_value=clear_value)
        decoded = self.log_debug_control("Enable-off CLA request readback", readback)
        self.check_debug_control_fields(
            decoded,
            {"cla_clock_stop": 1, "cla_clock_stop_en": 0, "jtag_clock_stop": 0},
            context=en_off_context,
        )
        await self.set_clk_stop_requests(0)
        await self.wait_for_signal_value("stop_clks", 0, context="cla_clock_stop_en=0 released")
        readback = await self.read_debug_control(shift_value=clear_value)
        decoded = self.log_debug_control("Enable-off request cleared readback", readback)
        self.check_debug_control_fields(
            decoded, {"cla_clock_stop": 0}, context="cla_clock_stop_en=0 released"
        )

        self.log_step(6, "Set JTAG_CLOCK_STOP alone, then add and clear a seeded CLA request")
        # Every read shifts jtag_value back in, so JTAG_CLOCK_STOP stays set
        # across this step.
        jtag_value = self.pack_debug_control(jtag_clock_stop=1)
        await self.write_debug_control(jtag_value)
        await self.wait_sys_cycles()
        await self.wait_for_signal_value("stop_clks", 1, context="jtag_clock_stop=1")
        readback = await self.read_debug_control(shift_value=jtag_value)
        decoded = self.log_debug_control("JTAG stop readback", readback)
        self.check_debug_control_fields(
            decoded, {"jtag_clock_stop": 1, "cla_clock_stop": 0}, context="jtag_clock_stop=1"
        )
        jtag_mask = self.rng("cla_clk_stop_mask_jtag").randint(1, full_mask)
        jtag_context = f"jtag_clock_stop=1 xtrig_clk_stop_req=0x{jtag_mask:03x}"
        await self.set_clk_stop_requests(jtag_mask)
        readback = await self.read_debug_control(shift_value=jtag_value)
        decoded = self.log_debug_control("JTAG stop with CLA request readback", readback)
        self.check_debug_control_fields(
            decoded, {"jtag_clock_stop": 1, "cla_clock_stop": 1}, context=jtag_context
        )
        await self.expect_dbg_signal("stop_clks", 1, context=jtag_context)
        await self.set_clk_stop_requests(0)
        readback = await self.read_debug_control(shift_value=jtag_value)
        decoded = self.log_debug_control("JTAG stop request cleared readback", readback)
        self.check_debug_control_fields(
            decoded,
            {"jtag_clock_stop": 1, "cla_clock_stop": 0},
            context="jtag_clock_stop=1 xtrig_clk_stop_req=0",
        )
        await self.expect_dbg_signal("stop_clks", 1, context="JTAG_CLOCK_STOP holds")
        await self.write_debug_control(clear_value)
        await self.wait_sys_cycles()
        await self.wait_for_signal_value("stop_clks", 0, context="jtag_clock_stop=0")
        self.check_stop_clks_off_edge(off_edge_start, context="whole pass")

        self.log_summary(
            "CLA clock-stop complete",
            enabled_control=f"0x{control_value:02x}",
            request_masks=",".join(f"0x{mask:03x}" for mask in request_masks),
            enable_off_mask=f"0x{en_off_mask:03x}",
            jtag_stop_mask=f"0x{jtag_mask:03x}",
        )
        await self.finalize_family_checker()
