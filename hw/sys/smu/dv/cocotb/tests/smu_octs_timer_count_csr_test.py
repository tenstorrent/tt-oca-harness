# SPDX-License-Identifier: Apache-2.0
"""smu_octs_timer_count_csr_test - P4 OCTS timer count advances via JTAG2AXI.

Start system_timer_octs, wait N cycles, prove TIMER_COUNT advances and
optional tb_timer_count pin tracks CSR. Dual-chiplet OCTS sync remains OUT.

32-bit CSRs on the 64-bit fabric: odd dword addresses (addr[2]=1) use the
upper data lane (wstrb=0xF0 / rdata>>32), matching WDT KEY / other SMU tests.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

OCTS_TIMER_START = 0xC000_E000
OCTS_CTRL = 0xC000_E004
OCTS_STATUS = 0xC000_E008
OCTS_PRESET_LO = 0xC000_E00C
OCTS_PRESET_HI = 0xC000_E010
OCTS_COUNT_LO = 0xC000_E014
OCTS_COUNT_HI = 0xC000_E018

STATUS_RUNNING = 0x10
WAIT_CYCLES = 256


def _wr32(addr: int, data: int) -> dict:
    """Lane-correct 32b write kwargs for 64b JTAG2AXI."""
    if addr & 0x4:
        return {
            "data": (int(data) & 0xFFFF_FFFF) << 32,
            "wstrb": 0xF0,
            "size": SMC_DBG_AXSIZE_4B,
        }
    return {
        "data": int(data) & 0xFFFF_FFFF,
        "wstrb": 0x0F,
        "size": SMC_DBG_AXSIZE_4B,
    }


def _rd32(addr: int, rdata: int) -> int:
    """Extract 32b payload from 64b JTAG2AXI rdata for ``addr``."""
    if addr & 0x4:
        return (int(rdata) >> 32) & 0xFFFF_FFFF
    return int(rdata) & 0xFFFF_FFFF


@pyuvm.test()
class smu_octs_timer_count_csr_test(smu_base_test):
    """OCTS CSR start + count advance (+ pin match)."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        count0 = count1 = 0
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            PRESET = 0x100
            st_p, _ = await jtag2axi_single_write(
                jtag, OCTS_PRESET_LO, **_wr32(OCTS_PRESET_LO, PRESET)
            )
            sb.expect_eq("OCTS preset_lo status", st_p, J2A_STATUS_SUCCESS)
            st_pr, preset_raw = await jtag2axi_single_read(
                jtag, OCTS_PRESET_LO, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("OCTS preset_lo readback status", st_pr, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "OCTS preset_lo programmed",
                _rd32(OCTS_PRESET_LO, preset_raw),
                PRESET,
            )
            st_ph, _ = await jtag2axi_single_write(
                jtag, OCTS_PRESET_HI, **_wr32(OCTS_PRESET_HI, 0)
            )
            sb.expect_eq("OCTS preset_hi status", st_ph, J2A_STATUS_SUCCESS)

            st_s, _ = await jtag2axi_single_write(
                jtag, OCTS_TIMER_START, **_wr32(OCTS_TIMER_START, 1)
            )
            sb.expect_eq("OCTS_CSR_OKAY start", st_s, J2A_STATUS_SUCCESS)

            await ClockCycles(dut.clk_smu_i, 8)
            st_st, status_raw = await jtag2axi_single_read(
                jtag, OCTS_STATUS, size=SMC_DBG_AXSIZE_4B
            )
            status = _rd32(OCTS_STATUS, status_raw)
            sb.expect_eq("OCTS status read", st_st, J2A_STATUS_SUCCESS)
            sb.expect_true(
                f"OCTS RUNNING (STATUS=0x{status:08x})",
                bool(status & STATUS_RUNNING),
            )

            st0, c0 = await jtag2axi_single_read(
                jtag, OCTS_COUNT_LO, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("OCTS count_lo read0", st0, J2A_STATUS_SUCCESS)
            st0h, c0h = await jtag2axi_single_read(
                jtag, OCTS_COUNT_HI, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("OCTS count_hi read0", st0h, J2A_STATUS_SUCCESS)
            count0 = (_rd32(OCTS_COUNT_HI, c0h) << 32) | _rd32(OCTS_COUNT_LO, c0)
            pin0 = int(dut.tb_timer_count.value) & 0xFFFF_FFFF_FFFF_FFFF

            await ClockCycles(dut.clk_smu_i, WAIT_CYCLES)

            st1, c1 = await jtag2axi_single_read(
                jtag, OCTS_COUNT_LO, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("OCTS count_lo read1", st1, J2A_STATUS_SUCCESS)
            st1h, c1h = await jtag2axi_single_read(
                jtag, OCTS_COUNT_HI, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("OCTS count_hi read1", st1h, J2A_STATUS_SUCCESS)
            count1 = (_rd32(OCTS_COUNT_HI, c1h) << 32) | _rd32(OCTS_COUNT_LO, c1)
            pin1 = int(dut.tb_timer_count.value) & 0xFFFF_FFFF_FFFF_FFFF

            # CSR advance is required; pin-only advance must not vacuous-PASS.
            sb.expect_true(
                f"OCTS_COUNT_ADVANCE csr {count0}->{count1}",
                count1 > count0,
                evidence="OCTS_COUNT_ADVANCE",
            )
            # Pin keeps ticking during JTAG2AXI read latency; require pin ahead
            # of CSR by a bounded amount (not a same-cycle equality).
            sb.expect_true(
                f"OCTS_PIN_MATCH pin=0x{pin1:x} >= csr=0x{count1:x}",
                pin1 >= count1 and (pin1 - count1) < 8192,
                evidence="OCTS_PIN_MATCH",
            )

            st_ctrl, _ = await jtag2axi_single_read(
                jtag, OCTS_CTRL, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("OCTS CTRL readable", st_ctrl, J2A_STATUS_SUCCESS)
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_octs_timer_count_csr_test: OCTS_COUNT_ADVANCE %d -> %d",
            count0,
            count1,
        )
