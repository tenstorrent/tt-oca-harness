# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_otp_debug_access_test - SMC OTP-over-JTAG CAPS + gated status.

SEP=0 ties feat_ctrl so OTP JTAG2AXI is gated. Bank responders are tied off.
Evidence (no vacuous PASS):

  1. SMC_OTP_JTAG2AXI_CAPS matches 32b/32b AXI-Lite encoding
  2. Force(security_disable=1): SINGLE_OP update ignored -> status != BUSY
     (gated idle completion) and not a hanging transaction
  3. Force(security_disable=0): SINGLE_OP starts AXI -> status stays BUSY
     (no bank response) for the full poll window
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS,
    J2A_STATUS_BUSY,
    SMC_OTP_DEFAULT_PROBE_ADDR,
    force_otp_jtag2axi_lifecycle_disable,
    force_otp_jtag2axi_lifecycle_enable,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    pack_otp_single_op,
    unpack_otp_single_op,
    J2A_OP_READ,
    SMC_OTP_AXSIZE_4B,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()


async def _otp_read_status_trace(jtag, addr: int, poll_limit: int) -> list[int]:
    """Issue OTP read and return the list of polled status values."""
    raw = pack_otp_single_op(J2A_OP_READ, addr, 0, wstrb=0, size=SMC_OTP_AXSIZE_4B)
    await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
    await ClockCycles(cocotb.top.clk_smu_i, 32)
    statuses: list[int] = []
    for _ in range(poll_limit):
        capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
        status, _ = unpack_otp_single_op(capt)
        statuses.append(status)
        if status != J2A_STATUS_BUSY:
            break
        await ClockCycles(cocotb.top.clk_smu_i, 16)
    return statuses


@pyuvm.test()
class smu_dtp_otp_debug_access_test(smu_base_test):
    """OTP CAPS + gated idle vs ungated BUSY (started, no bank) evidence."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        caps = await jtag.read("SMC_OTP_JTAG2AXI_CAPS", shift_value=0)
        sb.expect_eq(
            "SMC_OTP_JTAG2AXI_CAPS encoding",
            int(caps) & ((1 << 14) - 1),
            DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS,
        evidence="OTP_MAP_RW_OK")

        # --- Gated: update ignored -> must leave BUSY quickly ---
        forced_dis = force_otp_jtag2axi_lifecycle_disable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 8)
            for _ in range(8):
                await jtag.step_tms(0)
            gated = await _otp_read_status_trace(
                jtag, SMC_OTP_DEFAULT_PROBE_ADDR, poll_limit=16
            )
            # Precondition guard for gated[-1] below, not a scoreboard check:
            # "we collected samples" is test-setup, not RTL evidence. The real
            # evidence is the BUSY-status expect check that follows.
            assert gated, "OTP gated read produced no status samples"
            sb.expect_true(
                f"OTP gated leaves BUSY (statuses={gated})",
                gated[-1] != J2A_STATUS_BUSY,
            )
        finally:
            release_forced(forced_dis)

        # --- Ungated: transaction starts; tied bank keeps BUSY ---
        forced_en = force_otp_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)
            ungated = await _otp_read_status_trace(
                jtag, SMC_OTP_DEFAULT_PROBE_ADDR, poll_limit=32
            )
            # Precondition guard, not a scoreboard check (see gated case). The
            # real evidence is the "stays BUSY" expect check that follows, which
            # already requires len(ungated) >= 8.
            assert ungated, "OTP ungated read produced no status samples"
            sb.expect_true(
                f"OTP ungated stays BUSY (started, no bank; statuses={ungated})",
                all(s == J2A_STATUS_BUSY for s in ungated) and len(ungated) >= 8,
            )
        finally:
            release_forced(forced_en)

        self.logger.info(
            "smu_dtp_otp_debug_access_test: CAPS + gated/ungated status contrast OK"
        )
