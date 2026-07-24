# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_jtag2axi_wstrb_partial_sticky_test - P3-H2a partial WSTRB + neighbor.

Extends P2 SIZE/WSTRB matrix with adjacent-word isolation on outbound RAM:

  1. Seed word A and neighbor B
  2. Partial WSTRB update on A only
  3. A merges correctly; B unchanged
  4. Sticky SUCCESS on re-capture

Must FAIL if neighbor beat changes or merge wrong.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    PASS_RW_CONFIG,
    program_inbound0_window,
)
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

OUTBOUND0_FILTER_CONFIG = 0xC001_6000
OUTBOUND0_START = 0xC001_6008
OUTBOUND0_END = 0xC001_6010

FABRIC_A = 0x0200_0200
FABRIC_B = 0x0200_0208  # adjacent 8B beat
SEED_A = 0x1111_2222_3333_4444
SEED_B = 0xAAAA_BBBB_CCCC_DDDD
PARTIAL = 0xFFFF_0000_FFFF_0000
WSTRB = 0x55  # update even bytes only


def _apply_wstrb(prev: int, data: int, wstrb: int, nbytes: int = 8) -> int:
    out = int(prev)
    for byte_idx in range(nbytes):
        if (wstrb >> byte_idx) & 1:
            shift = 8 * byte_idx
            out = (out & ~(0xFF << shift)) | (((int(data) >> shift) & 0xFF) << shift)
    return out


@pyuvm.test()
class smu_dtp_jtag2axi_wstrb_partial_sticky_test(smu_base_test):
    """Partial WSTRB merge with adjacent fabric word isolation."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            await program_inbound0_window(
                jtag, 0, PASS_ALL_END, config=PASS_RW_CONFIG, scoreboard=sb
            )
            for addr, data, name in (
                (OUTBOUND0_START, 0x0, "OUTBOUND0_START"),
                (OUTBOUND0_END, PASS_ALL_END, "OUTBOUND0_END"),
                (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "OUTBOUND0_CONFIG"),
            ):
                st, _ = await jtag2axi_single_write(jtag, addr, data)
                sb.expect_eq(f"filter {name}", st, J2A_STATUS_SUCCESS)

            # Seed A and neighbor B (full strobes).
            for addr, seed, name in (
                (FABRIC_A, SEED_A, "A"),
                (FABRIC_B, SEED_B, "B"),
            ):
                st, _ = await jtag2axi_single_write(
                    jtag, addr, seed, wstrb=0xFF, size=3
                )
                sb.expect_eq(f"seed {name} status", st, J2A_STATUS_SUCCESS)

            # Partial update on A only.
            st_w, _ = await jtag2axi_single_write(
                jtag, FABRIC_A, PARTIAL, wstrb=WSTRB, size=3
            )
            sb.expect_eq("partial A write status", st_w, J2A_STATUS_SUCCESS)

            st_a, ra = await jtag2axi_single_read(jtag, FABRIC_A, size=3)
            sb.expect_eq("partial A read status", st_a, J2A_STATUS_SUCCESS)
            expect_a = _apply_wstrb(SEED_A, PARTIAL, WSTRB)
            sb.expect_eq(
                "partial A merged readback",
                int(ra) & 0xFFFF_FFFF_FFFF_FFFF,
                expect_a,
            )

            st_b, rb = await jtag2axi_single_read(jtag, FABRIC_B, size=3)
            sb.expect_eq("neighbor B read status", st_b, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "neighbor B unchanged",
                int(rb) & 0xFFFF_FFFF_FFFF_FFFF,
                SEED_B,
            )

            capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            sb.expect_eq(
                "sticky SUCCESS after partial",
                int(capt) & 0x3,
                J2A_STATUS_SUCCESS,
            )

            self.logger.info(
                "smu_dtp_jtag2axi_wstrb_partial_sticky_test: merge+neighbor OK "
                "(A=0x%x)",
                expect_a,
            )
        finally:
            release_forced(forced)
