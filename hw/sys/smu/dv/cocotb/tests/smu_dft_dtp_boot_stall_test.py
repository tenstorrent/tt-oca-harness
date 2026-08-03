# SPDX-License-Identifier: Apache-2.0
"""smu_dft_dtp_boot_stall_test - DTP DEBUG_CONTROL boot-stall -> SMC fuse_reset.

Real checkers (must FAIL if wrong):
  1. DEBUG_CONTROL write updates jtag_boot_stall_ovrd / jtag_boot_stall
  2. TDR readback matches written fields
  3. With stall asserted across cold reset (TRST held deasserted),
     fuse_reset_n_delayed_o stays low until stall cleared
  4. Sticky: re-asserting stall after release does not re-gate fuse_reset
"""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_jtag_vip import OcahJtagDevice, OcahJtagTap
from cocotb.triggers import ClockCycles

from seq_lib.smu_axi_helpers import wait_signal_high
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
class smu_dft_dtp_boot_stall_test(smu_base_test):
    """DTP boot-stall override gates SMC fuse_reset with sticky release."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = _make_ptap(dut, self.cfg.jtag_period_ns, regs=("DEBUG_CONTROL",))
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        # --- Phase A: DEBUG_CONTROL <-> DTP outputs ---
        sb.expect_eq("boot_stall_ovrd idle", int(dut.jtag_boot_stall_ovrd.value), 0, evidence="STALL_COLD_STICKY")
        sb.expect_eq("boot_stall idle", int(dut.jtag_boot_stall.value), 0, evidence="STALL_TRST_CLEAR")
        sb.expect_eq(
            "fuse_reset after bring-up",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        combinations = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for ovrd, stall in combinations:
            value = _pack_debug_control(boot_stall_ovrd=ovrd, boot_stall=stall)
            await jtag.write("DEBUG_CONTROL", value)
            await ClockCycles(dut.clk_smu_i, 8)
            sb.expect_eq(
                f"jtag_boot_stall_ovrd combo ovrd={ovrd} stall={stall}",
                int(dut.jtag_boot_stall_ovrd.value),
                ovrd,
            )
            sb.expect_eq(
                f"jtag_boot_stall combo ovrd={ovrd} stall={stall}",
                int(dut.jtag_boot_stall.value),
                stall,
            )
            readback = await jtag.read("DEBUG_CONTROL", shift_value=value)
            sb.expect_eq(
                f"DEBUG_CONTROL readback ovrd={ovrd} stall={stall}",
                int(readback) & 0xF,
                value & 0xF,
            )

        # --- Phase B: SMC fuse_reset gating across cold reset ---
        await jtag.write(
            "DEBUG_CONTROL",
            _pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall asserted ovrd", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("stall asserted val", int(dut.jtag_boot_stall.value), 1)

        # Cold reset pulse; keep powergood and TRST high so DEBUG_CONTROL persists.
        self.logger.info("Pulsing rst_cold_ni with boot-stall held (TRST stays high)")
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            dut.rst_primary_smc_clk_no,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary_smc_clk_no after stall reset",
        )
        await ClockCycles(dut.clk_smu_i, 64)

        sb.expect_eq(
            "jtag_boot_stall_ovrd survives cold reset",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "jtag_boot_stall survives cold reset",
            int(dut.jtag_boot_stall.value),
            1,
        )
        sb.expect_eq(
            "fuse_reset gated while stall sticky",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # Release stall -> fuse_reset must rise.
        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall cleared ovrd", int(dut.jtag_boot_stall_ovrd.value), 0)
        sb.expect_eq("stall cleared val", int(dut.jtag_boot_stall.value), 0)
        await wait_signal_high(
            dut.fuse_reset_n_delayed_o,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="fuse_reset_n_delayed_o after stall clear",
        )
        sb.expect_eq(
            "fuse_reset released after stall clear",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        # Sticky: re-assert stall must NOT re-gate fuse_reset until next primary reset.
        await jtag.write(
            "DEBUG_CONTROL",
            _pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 64)
        sb.expect_eq(
            "fuse_reset stays high on sticky re-assert",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        await jtag.write("DEBUG_CONTROL", 0)
        await ClockCycles(dut.clk_smu_i, 8)
        self.logger.info("smu_dft_dtp_boot_stall_test: DTP+SMC boot-stall checks done")
