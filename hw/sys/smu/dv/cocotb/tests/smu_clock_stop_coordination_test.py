# SPDX-License-Identifier: Apache-2.0
"""smu_clock_stop_coordination_test - DEBUG_CONTROL + xtrig clock-stop.

Real checkers:
  1. DEBUG_CONTROL jtag_clock_stop updates dtp_stop_clks_o
  2. DEBUG_CONTROL cla_clock_stop_en updates dtp_cla_clock_stop_en
  3. xtrig_clk_stop_req[0] remaps into DTP clk_stop_req[1]
  4. TDR readback matches written clock-stop fields
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_jtag_helpers import make_smu_jtag_tap, pack_debug_control
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()


@pyuvm.test()
class smu_clock_stop_coordination_test(smu_base_test):
    """DTP DEBUG_CONTROL clock-stop and SMU xtrig remap evidence."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq("dtp_stop_clks idle", int(dut.dtp_stop_clks_o.value), 0, evidence="CLA_CLK_STOP_LOOP")
        sb.expect_eq(
            "dtp_cla_clock_stop_en idle", int(dut.dtp_cla_clock_stop_en.value), 0
        )

        # CLA enable bit alone must appear on hierarchical observe.
        # CLA fb path (dtp_xtrig_clk_stop_req[0]) stays 0 without real CLA halt —
        # that is observe of the product glue, not Force inject.
        val_cla = pack_debug_control(cla_clock_stop_en=1)
        await jtag.write("DEBUG_CONTROL", val_cla)
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq(
            "cla_clock_stop_en asserted", int(dut.dtp_cla_clock_stop_en.value), 1
        )
        sb.expect_eq(
            "CLA fb bit[0] idle without halt",
            int(dut.u_dut.dtp_xtrig_clk_stop_req.value) & 0x1,
            0,
            evidence="CLA_CLK_STOP_LOOP",
        )
        rb = await jtag.read("DEBUG_CONTROL", shift_value=val_cla)
        sb.expect_eq("DEBUG_CONTROL CLA readback", int(rb) & 0xF, val_cla & 0xF)

        # JTAG clock-stop drives stop_clks_o through CTN.
        val_stop = pack_debug_control(jtag_clock_stop=1, cla_clock_stop_en=1)
        await jtag.write("DEBUG_CONTROL", val_stop)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("jtag_clock_stop -> dtp_stop_clks_o", int(dut.dtp_stop_clks_o.value), 1)
        rb2 = await jtag.read("DEBUG_CONTROL", shift_value=val_stop)
        sb.expect_eq("DEBUG_CONTROL stop readback", int(rb2) & 0xF, val_stop & 0xF)

        # Clear JTAG stop; CLA enable may remain.
        val_clr = pack_debug_control(cla_clock_stop_en=1, jtag_clock_stop=0)
        await jtag.write("DEBUG_CONTROL", val_clr)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("dtp_stop_clks cleared", int(dut.dtp_stop_clks_o.value), 0)

        # Remap: TB xtrig_clk_stop_req[7:0] -> DTP[8:1]
        dtp_clk_stop = dut.u_dut.dtp_xtrig_clk_stop_req
        for bit in range(8):
            pat = 1 << bit
            dut.xtrig_clk_stop_req.value = pat
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)
            dtp = int(dtp_clk_stop.value)
            sb.expect_eq(
                f"xtrig_clk_stop bit{bit} -> DTP[8:1]",
                (dtp >> 1) & 0xFF,
                pat,
            )
        dut.xtrig_clk_stop_req.value = 0

        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("cla_clock_stop_en cleared", int(dut.dtp_cla_clock_stop_en.value), 0)

        self.logger.info("smu_clock_stop_coordination_test: DEBUG_CONTROL + remap OK")
