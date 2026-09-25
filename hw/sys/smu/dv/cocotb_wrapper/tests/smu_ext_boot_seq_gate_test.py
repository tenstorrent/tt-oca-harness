# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ext_boot_seq_gate_test — SMU P0 external boot-sequence gate (SMU_006).

DV-CARD:          SMU_006   ANCHOR: smu_ext_boot_seq_gate_test
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from seq_lib.smu_ext_boot_seq_gate_test_seq import smu_ext_boot_seq_gate_test_seq
from seq_lib.smu_tb_pins import smu_axi_in_prefix
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_ext_boot_seq_gate_test(smu_base_test):
    """SMU_006: ext_boot_seq_done_i gates smc_fuse_reset_n_delayed_o release."""

    use_shared_env = True

    async def bring_up(self) -> None:
        """Clocks + cold release with boot gate held at 0 (card S1)."""
        dut = cocotb.top
        cocotb.start_soon(Clock(dut.clk_smu_i, self.cfg.smu_clk_period_ns, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, unit="ns").start())
        cocotb.start_soon(Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, unit="ns").start())

        dut.ext_boot_seq_done_i.value = 0
        dut.jtag_tck.value = 0
        dut.jtag_tms.value = 1
        dut.jtag_tdi.value = 0
        if hasattr(dut, "xtrig_ctm_dst_req"):
            dut.xtrig_ctm_dst_req.value = 0
        if hasattr(dut, "xtrig_ctm_src_ack"):
            dut.xtrig_ctm_src_ack.value = 0
        if hasattr(dut, "xtrig_clk_stop_req"):
            dut.xtrig_clk_stop_req.value = 0
        if hasattr(dut, "captured_straps_i"):
            dut.captured_straps_i.value = 0
        if hasattr(dut, "gpio_boot_stall_drive_i"):
            dut.gpio_boot_stall_drive_i.value = 0
        # The per-pad drive enables are among the idle inputs; left undriven on
        # a four-state simulator they put X on every pad, and pad 57 is the
        # boot-stall input whose sticky flop then holds fuse_reset_n_delayed_o
        # at X once the boot gate opens.
        self.drive_idle_inputs()
        # Prefix, not literal names: this TB calls the same slave ext_in_*.
        axi = smu_axi_in_prefix(dut)
        for suffix in ("awvalid", "wvalid", "bready", "arvalid", "rready"):
            getattr(dut, f"{axi}_{suffix}").value = 0

        await self.arm_async_resets()
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0

        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Asserting powergood (boot gate ext_boot_seq_done_i=0)")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, 64)
        self.logger.info("Releasing cold reset (primary gated by ext_boot_seq_done_i)")
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.jtag_tap_reset(16)
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        self.cfg.reset_done.set()
        self.logger.info("SMU_006 bring-up: clocks running; boot gate=0; cold released")

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_ext_boot_seq_gate_test SMU_006")
        seq = smu_ext_boot_seq_gate_test_seq(self)
        await seq.run()
