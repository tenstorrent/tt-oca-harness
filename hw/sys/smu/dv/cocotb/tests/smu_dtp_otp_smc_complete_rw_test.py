# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_otp_smc_complete_rw_test - P2-I2a OTP map complete R/W (real checkers).

SEP=0: ungated OTP JTAG2AXI reaches SMC eFuse INTERFACE (shadow map). Relative
0x80 (P1 probe) hits SHIM with bank tied-off and hangs — use absolute MAP
addr 0xC000_B080 (BIRA, WRITE_UNLOCK).

Evidence (must FAIL if RDATA != shadow or gated still completes into map):

  1. Ungated OTP write SUCCESS to MAP BIRA word
  2. Ungated OTP read SUCCESS + RDATA == written pattern
  3. TB smc_shadow_regs word matches pattern (independent shadow)
  4. Fabric JTAG2AXI read of same addr matches (cross-path)
  5. Gated OTP write does not update shadow (idle SUCCESS is OK per P1)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_EFUSE_MAP_BIRA_WORD,
    force_otp_jtag2axi_lifecycle_disable,
    force_otp_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    otp_jtag2axi_single_write,
    release_forced,
    shadow_map_word32,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

PATTERN_A = 0xA5A5_5A5A
PATTERN_B = 0x5A5A_A5A5
MAP_BYTE_OFF = SMC_EFUSE_MAP_BIRA_WORD & 0xFFF  # 0x80 within 3KB map


@pyuvm.test()
class smu_dtp_otp_smc_complete_rw_test(smu_base_test):
    """OTP->SMC eFuse map complete write/read + gated contrast."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        # One packed Force covers OTP (fuse|soc|ap) and fabric (soc|ap). Do not
        # Release between phases — Verilator cannot stack Forces on one net.
        en = force_otp_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            # --- Ungated complete write ---
            wst, _ = await otp_jtag2axi_single_write(
                jtag, SMC_EFUSE_MAP_BIRA_WORD, PATTERN_A
            )
            sb.expect_eq("OTP ungated write status", wst, J2A_STATUS_SUCCESS, evidence="OTP_MAP_RW_OK")

            # --- Ungated complete read ---
            rst, rdata = await otp_jtag2axi_single_read(
                jtag, SMC_EFUSE_MAP_BIRA_WORD
            )
            sb.expect_eq("OTP ungated read status", rst, J2A_STATUS_SUCCESS, evidence="OTP_GATED_NO_UPDATE")
            sb.expect_eq(
                "OTP ungated RDATA == PATTERN_A",
                int(rdata) & 0xFFFF_FFFF,
                PATTERN_A,
            )

            # --- Independent shadow (TB port; fuse_sense_done already 1) ---
            shadow = shadow_map_word32(dut, MAP_BYTE_OFF)
            assert shadow is not None, "smc_shadow_regs not VPI-readable"
            sb.expect_eq("smc_shadow_regs BIRA word == PATTERN_A", shadow, PATTERN_A)

            # --- Cross-path: fabric debug JTAG2AXI sees same map word ---
            fst, frdata = await jtag2axi_single_read(jtag, SMC_EFUSE_MAP_BIRA_WORD)
            sb.expect_eq("fabric JTAG2AXI MAP status", fst, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "fabric MAP shadow == PATTERN_A",
                int(frdata) & 0xFFFF_FFFF,
                PATTERN_A,
            )

            # --- Gate OTP only (clear fuse_test; keep soc|ap for fabric) ---
            force_otp_jtag2axi_lifecycle_disable(dut, self.logger)
            await ClockCycles(dut.clk_smu_i, 8)
            for _ in range(8):
                await jtag.step_tms(0)
            gst, _ = await otp_jtag2axi_single_write(
                jtag, SMC_EFUSE_MAP_BIRA_WORD, PATTERN_B, poll_limit=16
            )
            self.logger.info("OTP gated write status=%s (idle SUCCESS OK)", gst)

            shadow_after = shadow_map_word32(dut, MAP_BYTE_OFF)
            assert shadow_after is not None, "smc_shadow_regs not VPI-readable after gate"
            sb.expect_eq(
                "shadow unchanged after gated write (still PATTERN_A)",
                shadow_after,
                PATTERN_A,
            )
            sb.expect_true(
                "gated write did not land PATTERN_B in shadow",
                shadow_after != PATTERN_B,
            )

            await ClockCycles(dut.clk_smu_i, 8)
            for _ in range(8):
                await jtag.step_tms(0)
            fst2, frdata2 = await jtag2axi_single_read(
                jtag, SMC_EFUSE_MAP_BIRA_WORD
            )
            sb.expect_eq("fabric re-read status after gated", fst2, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "fabric MAP still PATTERN_A after gated write",
                int(frdata2) & 0xFFFF_FFFF,
                PATTERN_A,
            )
        finally:
            release_forced(en)

        self.logger.info(
            "smu_dtp_otp_smc_complete_rw_test: OTP map R/W + gated contrast OK "
            "(addr=0x%08x)",
            SMC_EFUSE_MAP_BIRA_WORD,
        )
