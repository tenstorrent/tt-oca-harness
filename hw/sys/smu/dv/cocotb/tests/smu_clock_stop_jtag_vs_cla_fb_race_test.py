# SPDX-License-Identifier: Apache-2.0
"""smu_clock_stop_jtag_vs_cla_fb_race_test - P3-H6b JTAG stop || CLA fb OR.

stop_clks_o and DEBUG bit4 must follow the OR of JTAG clock_stop and CLA
feedback (with CLA en). Stimulus:

  1. JTAG stop alone -> stop_clks=1; bit3 set; bit4 may be 0 (CLA status)
  2. Clear JTAG stop; Force CLA fb with en -> stop_clks=1; bit4=1
  3. Both sources asserted -> stop_clks stays 1
  4. Clear JTAG stop while fb held -> still 1; release fb -> 0

Must FAIL if TDR / stop_clks disagree with OR of sources.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_jtag_helpers import (
    DBG_CLA_CLOCK_STOP_BIT,
    DBG_CLA_CLOCK_STOP_EN_BIT,
    DBG_JTAG_CLOCK_STOP_BIT,
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
class smu_clock_stop_jtag_vs_cla_fb_race_test(smu_base_test):
    """JTAG clock_stop OR CLA feedback must agree with stop_clks / TDR."""

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
                break
        assert fb is not None, "Could not resolve tdr_dbg_ctrl_clocks_stopped_by_cla"

        # --- 1) JTAG stop alone (CLA en for later) ---
        val_jtag = pack_debug_control(jtag_clock_stop=1, cla_clock_stop_en=1)
        await jtag.write("DEBUG_CONTROL", val_jtag)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("stop_clks from JTAG alone", int(dut.dtp_stop_clks_o.value), 1, evidence="CLOCK_STOP_OR")
        rb0 = await jtag.read("DEBUG_CONTROL", shift_value=val_jtag)
        sb.expect_eq(
            "DEBUG bit3 JTAG stop",
            (int(rb0) >> DBG_JTAG_CLOCK_STOP_BIT) & 1,
            1,
        )
        sb.expect_eq(
            "DEBUG bit2 CLA en",
            (int(rb0) >> DBG_CLA_CLOCK_STOP_EN_BIT) & 1,
            1,
        )

        # --- 2) Clear JTAG stop; Force CLA fb ---
        val_en = pack_debug_control(cla_clock_stop_en=1, jtag_clock_stop=0)
        await jtag.write("DEBUG_CONTROL", val_en)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("stop_clks cleared after JTAG off", int(dut.dtp_stop_clks_o.value), 0)

        fb.value = Force(1)
        try:
            for _ in range(8):
                await RisingEdge(dut.clk_smu_i)
            sb.expect_eq("stop_clks from CLA fb alone", int(dut.dtp_stop_clks_o.value), 1)
            rb1 = await jtag.read("DEBUG_CONTROL", shift_value=val_en)
            sb.expect_eq(
                "DEBUG bit4 CLA status with fb",
                (int(rb1) >> DBG_CLA_CLOCK_STOP_BIT) & 1,
                1,
            )
            sb.expect_eq(
                "DEBUG bit3 JTAG stop clear while fb",
                (int(rb1) >> DBG_JTAG_CLOCK_STOP_BIT) & 1,
                0,
            )

            # --- 3) Both: re-assert JTAG stop while fb held ---
            val_both = pack_debug_control(jtag_clock_stop=1, cla_clock_stop_en=1)
            await jtag.write("DEBUG_CONTROL", val_both)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq("stop_clks OR both sources", int(dut.dtp_stop_clks_o.value), 1)
            rb2 = await jtag.read("DEBUG_CONTROL", shift_value=val_both)
            sb.expect_eq(
                "DEBUG bit3 with both",
                (int(rb2) >> DBG_JTAG_CLOCK_STOP_BIT) & 1,
                1,
            )
            sb.expect_eq(
                "DEBUG bit4 with both",
                (int(rb2) >> DBG_CLA_CLOCK_STOP_BIT) & 1,
                1,
            )

            # --- 4) Clear JTAG; fb still holds stop ---
            await jtag.write("DEBUG_CONTROL", val_en)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                "stop_clks held by fb after JTAG clear",
                int(dut.dtp_stop_clks_o.value),
                1,
            )
        finally:
            fb.value = Release()

        for _ in range(16):
            await RisingEdge(dut.clk_smu_i)
        sb.expect_eq("stop_clks cleared after fb release", int(dut.dtp_stop_clks_o.value), 0)

        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)

        self.logger.info(
            "smu_clock_stop_jtag_vs_cla_fb_race_test: JTAG|CLA OR stop OK"
        )
