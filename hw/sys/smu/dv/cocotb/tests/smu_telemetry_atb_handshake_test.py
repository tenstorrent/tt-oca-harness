# SPDX-License-Identifier: Apache-2.0
"""smu_telemetry_atb_handshake_test - P4 telemetry ATB ch0 handshake.

Drive ATB channel-0 (atvalid/atdata/atid + afready), prove atready accepts
beats, then set CTRL.TELEMETRY_TX_FLUSH and prove afvalid handshake clears
the sticky flush bit.

CSR base: TELEMETRY_RECEIVER_0 @ 0xC000_D000.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

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

TEL0_CTRL = 0xC000_D000
TEL_TX_FLUSH = 0x100  # CTRL.TELEMETRY_TX_FLUSH bit8


@pyuvm.test()
class smu_telemetry_atb_handshake_test(smu_base_test):
    """ATB ready/valid + afvalid flush handshake on receiver 0."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()

        # Idle ATB.
        dut.tb_tel_atvalid.value = 0
        dut.tb_tel_afready.value = 0
        dut.tb_tel_atdata.value = 0
        dut.tb_tel_atid.value = 0

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            st0, ctrl0 = await jtag2axi_single_read(jtag, TEL0_CTRL)
            sb.expect_eq("TEL0 CTRL reset read", st0, J2A_STATUS_SUCCESS)
            sb.expect_eq("TEL0 CTRL reset 0", int(ctrl0) & 0xFFFF_FFFF, 0)

            # Wait for atready high (not flushing).
            saw_ready = False
            for _ in range(64):
                await RisingEdge(dut.clk_smu_i)
                if int(dut.tb_tel_atready.value) & 1:
                    saw_ready = True
                    break
            sb.expect_true("TEL_ATREADY idle high", saw_ready)

            # Drive a few ATB beats; latch that atready stayed high during valid.
            hs = 0
            dut.tb_tel_atid.value = 0x11
            for beat in (0xA5, 0x5A, 0x3C):
                dut.tb_tel_atdata.value = beat
                dut.tb_tel_atvalid.value = 1
                for _ in range(8):
                    await RisingEdge(dut.clk_smu_i)
                    if (int(dut.tb_tel_atvalid.value) & 1) and (
                        int(dut.tb_tel_atready.value) & 1
                    ):
                        hs += 1
                        break
                dut.tb_tel_atvalid.value = 0
                await RisingEdge(dut.clk_smu_i)

            sb.expect_true(
                f"TEL_ATREADY_HS beats={hs}",
                hs >= 3,
                evidence="TEL_ATREADY_HS",
            )

            # Flush path: set TELEMETRY_TX_FLUSH, see afvalid, ack with afready.
            st_w, _ = await jtag2axi_single_write(
                jtag,
                TEL0_CTRL,
                TEL_TX_FLUSH,
                wstrb=0x0F,
                size=SMC_DBG_AXSIZE_4B,
            )
            sb.expect_eq("TEL flush write status", st_w, J2A_STATUS_SUCCESS)

            saw_af = False
            for _ in range(64):
                await RisingEdge(dut.clk_smu_i)
                if int(dut.tb_tel_afvalid.value) & 1:
                    saw_af = True
                    break
            sb.expect_true("TEL_AFVALID_HS asserted", saw_af)

            dut.tb_tel_afready.value = 1
            for _ in range(16):
                await RisingEdge(dut.clk_smu_i)
                if (int(dut.tb_tel_afvalid.value) & 1) == 0:
                    break
            dut.tb_tel_afready.value = 0
            await ClockCycles(dut.clk_smu_i, 4)

            st1, ctrl1 = await jtag2axi_single_read(jtag, TEL0_CTRL)
            sb.expect_eq("TEL CTRL after flush ack", st1, J2A_STATUS_SUCCESS)
            sb.expect_true(
                f"flush cleared (CTRL=0x{int(ctrl1) & 0xFFFFFFFF:08x})",
                (int(ctrl1) & TEL_TX_FLUSH) == 0,
            )
        finally:
            dut.tb_tel_atvalid.value = 0
            dut.tb_tel_afready.value = 0
            release_forced(forced)

        self.logger.info(
            "smu_telemetry_atb_handshake_test: TEL_ATREADY_HS + TEL_AFVALID_HS OK"
        )
