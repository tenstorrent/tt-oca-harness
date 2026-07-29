# SPDX-License-Identifier: Apache-2.0
"""smc_cpu_traffic_ext_axi_test - SMC fabric -> external SMN outbound path.

Programs outbound (+inbound) filters via JTAG2AXI, then issues a fabric write to
the output-fabric window and checks:
  1. JTAG2AXI status SUCCESS
  2. ``smu_axi_out_awvalid_count`` advances (TB outbound RAM saw AW)
  3. JTAG2AXI readback matches written data

Baseline: count does not advance before the write (checker sensitivity).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

INBOUND0_FILTER_CONFIG = 0xC001_5000
INBOUND0_START = 0xC001_5008
INBOUND0_END = 0xC001_5010
OUTBOUND0_FILTER_CONFIG = 0xC001_6000
OUTBOUND0_START = 0xC001_6008
OUTBOUND0_END = 0xC001_6010
# Include ALLOW_NS (bit8) so non-secure masters are not rejected.
PASS_ALL_CONFIG = 0x0100_3113

OUTPUT_FABRIC_ADDR = 0x0200_0000
OUTPUT_FABRIC_DATA = 0x1122_3344_5566_7788


@pyuvm.test()
class smc_cpu_traffic_ext_axi_test(smu_base_test):
    """External outbound path: filter open + write increments AW + readback."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await ClockCycles(dut.clk_smu_i, 50)
        aw0 = int(dut.smu_axi_out_awvalid_count.value)

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            # Program inbound+outbound filters to pass the fabric address space.
            for addr, data, name in (
                (INBOUND0_START, 0x0, "INBOUND0_START"),
                (INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, "INBOUND0_END"),
                (INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, "INBOUND0_FILTER_CONFIG"),
                (OUTBOUND0_START, 0x0, "OUTBOUND0_START"),
                (OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, "OUTBOUND0_END"),
                (OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, "OUTBOUND0_FILTER_CONFIG"),
            ):
                status, _ = await jtag2axi_single_write(jtag, addr, data)
                sb.expect_eq(f"JTAG2AXI program {name} status", status, J2A_STATUS_SUCCESS, evidence="AXI_ID_WIDTH_OK")

            # Prove CONFIG stuck (not a vacuous SUCCESS without side-effect).
            st_cfg, cfg_rb = await jtag2axi_single_read(jtag, OUTBOUND0_FILTER_CONFIG)
            sb.expect_eq("OUTBOUND0_FILTER_CONFIG read status", st_cfg, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "OUTBOUND0_FILTER_CONFIG readback",
                int(cfg_rb) & 0xFFFF_FFFF,
                PASS_ALL_CONFIG & 0xFFFF_FFFF,
            )

            aw_before = int(dut.smu_axi_out_awvalid_count.value)
            sb.expect_eq(
                "outbound AW idle before traffic",
                aw_before,
                aw0,
            )

            status_w, _ = await jtag2axi_single_write(
                jtag, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_DATA
            )
            sb.expect_eq("JTAG2AXI outbound write status", status_w, J2A_STATUS_SUCCESS)
            await ClockCycles(dut.clk_smu_i, 32)
            aw1 = int(dut.smu_axi_out_awvalid_count.value)
            sb.expect_true(
                "smu_axi_out_awvalid_count advanced after outbound write",
                aw1 > aw_before,
            )

            status_r, rdata = await jtag2axi_single_read(jtag, OUTPUT_FABRIC_ADDR)
            sb.expect_eq("JTAG2AXI outbound read status", status_r, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "JTAG2AXI outbound readback data",
                int(rdata),
                OUTPUT_FABRIC_DATA,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smc_cpu_traffic_ext_axi_test: outbound AW %d->%d data=0x%x",
            aw0,
            int(dut.smu_axi_out_awvalid_count.value),
            OUTPUT_FABRIC_DATA,
        )
