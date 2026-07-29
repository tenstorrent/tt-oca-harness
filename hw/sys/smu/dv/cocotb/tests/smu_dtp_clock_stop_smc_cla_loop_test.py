# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_clock_stop_smc_cla_loop_test - P2-I6a CLA clock-stop feedback loop.

SMU glue (smu.sv):
  tdr_dbg_ctrl_clocks_stopped_by_cla -> dtp_xtrig_clk_stop_req[0]
  CTN OR -> stop_clks_o + DEBUG_CONTROL CLA_CLOCK_STOP (bit4) readback

P1 already covered DEBUG_CONTROL en/stop exports and TB xtrig[7:0]->DTP[8:1].
This deepener closes bit[0] feedback with real checkers (Force injects SMC
feedback; does not invent CLA halt microcode).

Evidence (must FAIL if stop_clks / CLA en / feedback disagree):

  1. CLA en alone: cla_en=1, stop_clks=0, fb=0, DEBUG bit4=0
  2. Force fb=1: dtp req[0]=1, stop_clks=1, DEBUG bit4=1
  3. Release fb: stop_clks=0, bit4=0 (en still 1)
  4. Clear en
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_jtag_helpers import (
    DBG_CLA_CLOCK_STOP_BIT,
    DBG_CLA_CLOCK_STOP_EN_BIT,
    make_smu_jtag_tap,
    pack_debug_control,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

_FB_CANDIDATES = (
    "u_dut.tdr_dbg_ctrl_clocks_stopped_by_cla",
)


def _resolve(dut, path: str):
    cur = dut
    for part in path.split("."):
        cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


@pyuvm.test()
class smu_dtp_clock_stop_smc_cla_loop_test(smu_base_test):
    """SMC CLA feedback -> DTP clk_stop_req[0] -> stop_clks + TDR bit4."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        fb = None
        for path in _FB_CANDIDATES:
            fb = _resolve(dut, path)
            if fb is not None:
                self.logger.info("CLA feedback observe/force path: %s", path)
                break
        assert fb is not None, "Could not resolve tdr_dbg_ctrl_clocks_stopped_by_cla"

        dtp_req = dut.u_dut.dtp_xtrig_clk_stop_req

        # --- 1) CLA enable alone: export en, no stop, no feedback ---
        val_en = pack_debug_control(cla_clock_stop_en=1)
        await jtag.write("DEBUG_CONTROL", val_en)
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq("cla_clock_stop_en asserted", int(dut.dtp_cla_clock_stop_en.value), 1, evidence="CLA_CLK_STOP_LOOP")
        sb.expect_eq("stop_clks idle with en-only", int(dut.dtp_stop_clks_o.value), 0)
        sb.expect_eq("SMC feedback idle with en-only", int(fb.value), 0)
        sb.expect_eq("DTP clk_stop_req[0] idle", int(dtp_req.value) & 0x1, 0)

        rb0 = await jtag.read("DEBUG_CONTROL", shift_value=val_en)
        sb.expect_eq(
            "DEBUG bit2 CLA en readback",
            (int(rb0) >> DBG_CLA_CLOCK_STOP_EN_BIT) & 1,
            1,
        )
        sb.expect_eq(
            "DEBUG bit4 CLA stop status idle",
            (int(rb0) >> DBG_CLA_CLOCK_STOP_BIT) & 1,
            0,
        )

        # --- 2) Inject SMC feedback (CLA halt status) ---
        fb.value = Force(1)
        try:
            for _ in range(8):
                await RisingEdge(dut.clk_smu_i)

            sb.expect_eq("DTP clk_stop_req[0] follows feedback", int(dtp_req.value) & 0x1, 1)
            sb.expect_eq("stop_clks follows feedback OR", int(dut.dtp_stop_clks_o.value), 1)

            rb1 = await jtag.read("DEBUG_CONTROL", shift_value=val_en)
            sb.expect_eq(
                "DEBUG bit4 CLA stop status with feedback",
                (int(rb1) >> DBG_CLA_CLOCK_STOP_BIT) & 1,
                1,
            )
            sb.expect_eq(
                "DEBUG bit2 CLA en sticky with feedback",
                (int(rb1) >> DBG_CLA_CLOCK_STOP_EN_BIT) & 1,
                1,
            )
        finally:
            fb.value = Release()

        # --- 3) Release feedback: stop clears, en remains ---
        for _ in range(16):
            await RisingEdge(dut.clk_smu_i)
        sb.expect_eq("stop_clks cleared after fb release", int(dut.dtp_stop_clks_o.value), 0)
        sb.expect_eq("DTP clk_stop_req[0] cleared", int(dtp_req.value) & 0x1, 0)
        sb.expect_eq("cla_en still asserted", int(dut.dtp_cla_clock_stop_en.value), 1)

        rb2 = await jtag.read("DEBUG_CONTROL", shift_value=val_en)
        sb.expect_eq(
            "DEBUG bit4 cleared after fb release",
            (int(rb2) >> DBG_CLA_CLOCK_STOP_BIT) & 1,
            0,
        )

        # --- 4) Clear en ---
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("cla_clock_stop_en cleared", int(dut.dtp_cla_clock_stop_en.value), 0)

        self.logger.info(
            "smu_dtp_clock_stop_smc_cla_loop_test: CLA feedback loop OK"
        )
