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
from ocah_jtag_vip import OcahJtagDevice, OcahJtagTap
from cocotb.triggers import ClockCycles, RisingEdge

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()


def _make_ptap(dut, period_ns: float, *, regs: tuple[str, ...] = ("DEBUG_CONTROL",)) -> OcahJtagTap:
    """Build OcahJtagTap against real TB JTAG pins (no Force / no fake DUT)."""
    device = OcahJtagDevice(
        name="smu_ptap",
        idcode=0x0000_0001,
        ir_width=6,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, 0x01)
    if "DEBUG_CONTROL" in regs:
        device.add_reg("DEBUG_CONTROL", 5, 0x18, write=True)
    if "IC_RESET" in regs:
        # SMU SEP=0: 69 ports * 2 + hold = 139
        device.add_reg("IC_RESET", 139, 0x0D, write=True)
    if "EXTEST" in regs:
        device.add_reg("EXTEST", 8, 0x04, write=True)
    jtag = OcahJtagTap(
        dut,
        name="smu_ptap",
        tck_period_ns=period_ns,
        ir_width=6,
        tap_type="ptap",
        signal_map={
            "tck": "jtag_tck",
            "tms": "jtag_tms",
            "tdi": "jtag_tdi",
            "tdo": "jtag_tdo",
            "trst": "jtag_trst",
            "tdo_oen": "jtag_tdo_oen",
        },
    )
    jtag.add_device(device)
    jtag.init_signals()
    return jtag

def _pack_debug_control(
    *,
    boot_stall: int = 0,
    boot_stall_ovrd: int = 0,
    cla_clock_stop_en: int = 0,
    jtag_clock_stop: int = 0,
) -> int:
    # DTP DEBUG_CONTROL TDR bit layout (real DTP TDR).
    return (
        ((boot_stall & 0x1) << 0)
        | ((boot_stall_ovrd & 0x1) << 1)
        | ((cla_clock_stop_en & 0x1) << 2)
        | ((jtag_clock_stop & 0x1) << 3)
    )

@pyuvm.test()
class smu_clock_stop_coordination_test(smu_base_test):
    """DTP DEBUG_CONTROL clock-stop and SMU xtrig remap evidence."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        # Real SMU RTL: bare u_dut == smu; wrapper u_dut.u_smu == smu.
        smu = dut.u_dut.u_smu if hasattr(dut.u_dut, "u_smu") else dut.u_dut

        jtag = _make_ptap(dut, self.cfg.jtag_period_ns, regs=("DEBUG_CONTROL",))
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
        val_cla = _pack_debug_control(cla_clock_stop_en=1)
        await jtag.write("DEBUG_CONTROL", val_cla)
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq(
            "cla_clock_stop_en asserted", int(dut.dtp_cla_clock_stop_en.value), 1
        )
        sb.expect_eq(
            "CLA fb bit[0] idle without halt",
            int(smu.dtp_xtrig_clk_stop_req.value) & 0x1,
            0,
            evidence="CLA_CLK_STOP_LOOP",
        )
        rb = await jtag.read("DEBUG_CONTROL", shift_value=val_cla)
        sb.expect_eq("DEBUG_CONTROL CLA readback", int(rb) & 0xF, val_cla & 0xF)

        # JTAG clock-stop drives stop_clks_o through CTN.
        val_stop = _pack_debug_control(jtag_clock_stop=1, cla_clock_stop_en=1)
        await jtag.write("DEBUG_CONTROL", val_stop)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("jtag_clock_stop -> dtp_stop_clks_o", int(dut.dtp_stop_clks_o.value), 1)
        rb2 = await jtag.read("DEBUG_CONTROL", shift_value=val_stop)
        sb.expect_eq("DEBUG_CONTROL stop readback", int(rb2) & 0xF, val_stop & 0xF)

        # Clear JTAG stop; CLA enable may remain.
        val_clr = _pack_debug_control(cla_clock_stop_en=1, jtag_clock_stop=0)
        await jtag.write("DEBUG_CONTROL", val_clr)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("dtp_stop_clks cleared", int(dut.dtp_stop_clks_o.value), 0)

        # Remap: TB xtrig_clk_stop_req[7:0] -> DTP[8:1]
        dtp_clk_stop = smu.dtp_xtrig_clk_stop_req
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
