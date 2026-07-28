# SPDX-License-Identifier: Apache-2.0
"""smu_cla_and_xtrig_concurrent_test - P3-H6a CLA stop_clks || CTM four-phase.

While CLA en+feedback holds stop_clks, run a legal dest four-phase on [9:2]:

  1. CLA en + Force fb -> stop_clks=1, DEBUG bit4=1
  2. Dest four-phase (req/ack/req-clear/ack-clear) on [9:2]
  3. Throughout: SMC[1:0] idle; stop_clks stays 1 (CTM must not drop stop)
  4. Release fb + clear en -> stop_clks=0

Must FAIL if stop_clks drops early during CTM or SMC[1:0] polluted.
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

DEST_PAT = 0xA5
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


def _u8(value: int) -> int:
    return int(value) & 0xFF


@pyuvm.test()
class smu_cla_and_xtrig_concurrent_test(smu_base_test):
    """CLA feedback stop_clks concurrent with CTM dest four-phase."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        dut.xtrig_ctm_dst_req.value = 0
        await ClockCycles(dut.clk_smu_i, 8)

        fb = None
        for path in _FB_CANDIDATES:
            fb = _resolve(dut, path)
            if fb is not None:
                break
        assert fb is not None, "Could not resolve tdr_dbg_ctrl_clocks_stopped_by_cla"

        dtp_dst_req = dut.u_dut.dtp_xtrig_ctm_dst_req
        dtp_dst_ack = dut.u_dut.dtp_xtrig_ctm_dst_ack

        async def _settle():
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

        # --- CLA en + feedback: stop_clks held ---
        val_en = pack_debug_control(cla_clock_stop_en=1)
        await jtag.write("DEBUG_CONTROL", val_en)
        await ClockCycles(dut.clk_smu_i, 8)
        fb.value = Force(1)
        try:
            for _ in range(8):
                await RisingEdge(dut.clk_smu_i)
            sb.expect_eq("stop_clks before CTM", int(dut.dtp_stop_clks_o.value), 1)
            rb0 = await jtag.read("DEBUG_CONTROL", shift_value=val_en)
            sb.expect_eq(
                "DEBUG bit4 before CTM",
                (int(rb0) >> DBG_CLA_CLOCK_STOP_BIT) & 1,
                1,
            )

            # --- Dest four-phase while stop held ---
            dut.xtrig_ctm_dst_req.value = DEST_PAT
            await _settle()
            sb.expect_eq(
                "CTM P1 DTP[9:2]",
                (int(dtp_dst_req.value) >> 2) & 0xFF,
                DEST_PAT,
            )
            sb.expect_eq("CTM P1 SMC[1:0]", int(dtp_dst_req.value) & 0x3, 0)
            sb.expect_eq(
                "stop_clks held at CTM P1",
                int(dut.dtp_stop_clks_o.value),
                1,
            )

            dtp_dst_ack.value = Force(DEST_PAT << 2)
            try:
                await _settle()
                sb.expect_eq(
                    "CTM P2 TB ack",
                    _u8(dut.xtrig_ctm_dst_ack.value),
                    DEST_PAT,
                )
                sb.expect_eq(
                    "CTM P2 SMC[1:0] on ack",
                    int(dtp_dst_ack.value) & 0x3,
                    0,
                )
                sb.expect_eq(
                    "stop_clks held at CTM P2",
                    int(dut.dtp_stop_clks_o.value),
                    1,
                )

                dut.xtrig_ctm_dst_req.value = 0
                await _settle()
                sb.expect_eq(
                    "CTM P3 req cleared",
                    (int(dtp_dst_req.value) >> 2) & 0xFF,
                    0,
                )
                sb.expect_eq(
                    "stop_clks held at CTM P3",
                    int(dut.dtp_stop_clks_o.value),
                    1,
                )
            finally:
                dtp_dst_ack.value = Release()

            await _settle()
            sb.expect_eq("CTM P4 ack cleared", _u8(dut.xtrig_ctm_dst_ack.value), 0)
            sb.expect_eq(
                "stop_clks held after CTM complete",
                int(dut.dtp_stop_clks_o.value),
                1,
            )
            sb.expect_eq(
                "SMC[1:0] idle after CTM",
                int(dtp_dst_req.value) & 0x3,
                0,
            )

            rb1 = await jtag.read("DEBUG_CONTROL", shift_value=val_en)
            sb.expect_eq(
                "DEBUG bit4 still 1 after CTM",
                (int(rb1) >> DBG_CLA_CLOCK_STOP_BIT) & 1,
                1,
            )
            sb.expect_eq(
                "DEBUG bit2 en sticky after CTM",
                (int(rb1) >> DBG_CLA_CLOCK_STOP_EN_BIT) & 1,
                1,
            )
        finally:
            fb.value = Release()

        for _ in range(16):
            await RisingEdge(dut.clk_smu_i)
        sb.expect_eq("stop_clks cleared after fb release", int(dut.dtp_stop_clks_o.value), 0)

        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("cla_en cleared", int(dut.dtp_cla_clock_stop_en.value), 0)

        self.logger.info(
            "smu_cla_and_xtrig_concurrent_test: CLA stop held through CTM OK"
        )
