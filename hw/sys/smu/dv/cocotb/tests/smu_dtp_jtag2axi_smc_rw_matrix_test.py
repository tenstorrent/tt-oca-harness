# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_jtag2axi_smc_rw_matrix_test - P2-I1a SIZE/WSTRB R/W matrix.

P1 local_axi proves VERSION_LO + one filter CSR. This deepener programs
inbound+outbound filters, then exercises SMC_AXI_SINGLE_OP against the TB
outbound RAM (WSTRB-aware) with:

  1. SIZE 0..3 directed write + readback (full strobes)
  2. SIZE=3 partial WSTRB 0x55 / 0xAA lane updates
  3. Sticky: completed status stays SUCCESS on re-capture (not BUSY)

Must FAIL if SIZE/WSTRB/addr mishandled or status sticks as BUSY.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_BUSY,
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
PASS_ALL_CONFIG = 0x0100_3113

# TB out_mem indexes addr[12:3]; keep traffic in low 8KB of fabric window.
FABRIC_BASE = 0x0200_0000
DEFAULT_DATA = 0x0123_4567_89AB_CDEF


def _size_bytes(size: int) -> int:
    return 1 << size


def _data_mask(size: int) -> int:
    return (1 << (8 * _size_bytes(size))) - 1


def _full_wstrb(size: int) -> int:
    return (1 << _size_bytes(size)) - 1


def _apply_wstrb(prev: int, data: int, wstrb: int, size: int) -> int:
    """Merge write data into prev for enabled lanes within transfer size."""
    out = prev
    for byte_idx in range(_size_bytes(size)):
        if (wstrb >> byte_idx) & 1:
            shift = 8 * byte_idx
            out = (out & ~(0xFF << shift)) | (((data >> shift) & 0xFF) << shift)
    return out


@pyuvm.test()
class smu_dtp_jtag2axi_smc_rw_matrix_test(smu_base_test):
    """JTAG2AXI SIZE/WSTRB matrix on SMC outbound fabric path."""

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

            # Open filters so fabric window is reachable from JTAG2AXI.
            for addr, data, name in (
                (INBOUND0_START, 0x0, "INBOUND0_START"),
                (INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, "INBOUND0_END"),
                (INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, "INBOUND0_FILTER_CONFIG"),
                (OUTBOUND0_START, 0x0, "OUTBOUND0_START"),
                (OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, "OUTBOUND0_END"),
                (OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, "OUTBOUND0_FILTER_CONFIG"),
            ):
                st, _ = await jtag2axi_single_write(jtag, addr, data)
                sb.expect_eq(f"filter program {name}", st, J2A_STATUS_SUCCESS, evidence="J2A_RW_MATRIX_OK")

            # --- 1) SIZE sweep: write + readback ---
            for idx, size in enumerate((0, 1, 2, 3)):
                addr = FABRIC_BASE + (idx * 0x40)
                data = (DEFAULT_DATA ^ (0x1111_1111_1111_1111 * idx)) & _data_mask(size)
                wstrb = _full_wstrb(size)
                st_w, _ = await jtag2axi_single_write(
                    jtag, addr, data, wstrb=wstrb, size=size
                )
                sb.expect_eq(f"SIZE{size} write status", st_w, J2A_STATUS_SUCCESS)
                st_r, rdata = await jtag2axi_single_read(jtag, addr, size=size)
                sb.expect_eq(f"SIZE{size} read status", st_r, J2A_STATUS_SUCCESS)
                sb.expect_eq(
                    f"SIZE{size} readback",
                    int(rdata) & _data_mask(size),
                    data,
                )

            # --- 2) Partial WSTRB on 8B beats ---
            for wstrb, tag in ((0x55, "even"), (0xAA, "odd")):
                addr = FABRIC_BASE + (0x140 if wstrb == 0x55 else 0x180)
                # Clear beat first.
                st_clr, _ = await jtag2axi_single_write(
                    jtag, addr, 0, wstrb=0xFF, size=3
                )
                sb.expect_eq(f"WSTRB {tag} clear status", st_clr, J2A_STATUS_SUCCESS)

                pattern = 0xA5A5_5A5A_C3C3_3C3C if wstrb == 0x55 else 0x5A5A_A5A5_3C3C_C3C3
                st_w, _ = await jtag2axi_single_write(
                    jtag, addr, pattern, wstrb=wstrb, size=3
                )
                sb.expect_eq(f"WSTRB {tag} write status", st_w, J2A_STATUS_SUCCESS)

                st_r, rdata = await jtag2axi_single_read(jtag, addr, size=3)
                sb.expect_eq(f"WSTRB {tag} read status", st_r, J2A_STATUS_SUCCESS)
                expected = _apply_wstrb(0, pattern, wstrb, 3)
                sb.expect_eq(
                    f"WSTRB {tag} merged readback",
                    int(rdata) & 0xFFFF_FFFF_FFFF_FFFF,
                    expected,
                )

            # --- 3) Sticky SUCCESS after completion (not stuck BUSY) ---
            capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            sticky_status = int(capt) & 0x3
            sb.expect_eq(
                "sticky post-matrix status SUCCESS",
                sticky_status,
                J2A_STATUS_SUCCESS,
            )
            sb.expect_true(
                f"sticky status not BUSY ({sticky_status})",
                sticky_status != J2A_STATUS_BUSY,
            )

            # Bridge still alive after matrix.
            st_v, r_v = await jtag2axi_single_read(jtag, 0xC000_2900)
            sb.expect_eq("VERSION_LO after matrix status", st_v, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "VERSION_LO after matrix data",
                int(r_v) & 0xFFFF_FFFF,
                0x0001_00A0,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_dtp_jtag2axi_smc_rw_matrix_test: SIZE/WSTRB matrix + sticky OK"
        )
