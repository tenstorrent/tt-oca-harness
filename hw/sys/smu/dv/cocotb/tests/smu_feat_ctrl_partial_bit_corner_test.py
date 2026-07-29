# SPDX-License-Identifier: Apache-2.0
"""smu_feat_ctrl_partial_bit_corner_test - P3-H4b incomplete OTP feat_ctrl.

OTP ungating requires fuse_test AND soc_debug AND ap_debug. Incomplete sets
must not complete a MAP write into the shadow:

  1. {fuse only}
  2. {soc, ap} without fuse
  3. {fuse, soc} without ap
  4. Contrast: {fuse, soc, ap} DOES write PATTERN

Must FAIL if any incomplete set lands PATTERN in smc_shadow_regs.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_EFUSE_MAP_BIRA_WORD,
    force_feat_ctrl_bits,
    make_smu_jtag_tap,
    otp_jtag2axi_single_write,
    release_forced,
    shadow_map_word32,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

MAP_BYTE_OFF = SMC_EFUSE_MAP_BIRA_WORD & 0xFFF
GATED_POLL = 16

# (label, bit_values, unique_pattern) — all incomplete for OTP
_INCOMPLETE = (
    ("fuse_only", {"fuse_test": 1, "soc_debug": 0, "ap_debug": 0}, 0xF05E_0001),
    ("soc_ap_no_fuse", {"fuse_test": 0, "soc_debug": 1, "ap_debug": 1}, 0x50CA_0002),
    ("fuse_soc_no_ap", {"fuse_test": 1, "soc_debug": 1, "ap_debug": 0}, 0xF050_0003),
)


@pyuvm.test()
class smu_feat_ctrl_partial_bit_corner_test(smu_base_test):
    """Incomplete feat_ctrl sets must not update OTP MAP shadow."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        before0 = shadow_map_word32(dut, MAP_BYTE_OFF)
        assert before0 is not None, "smc_shadow_regs not VPI-readable"

        for label, bits, pat in _INCOMPLETE:
            forced = force_feat_ctrl_bits(dut, bits, self.logger)
            try:
                await ClockCycles(dut.clk_smu_i, 8)
                for _ in range(4):
                    await jtag.step_tms(0)

                before = shadow_map_word32(dut, MAP_BYTE_OFF)
                assert before is not None
                st, _ = await otp_jtag2axi_single_write(
                    jtag, SMC_EFUSE_MAP_BIRA_WORD, pat, poll_limit=GATED_POLL
                )
                self.logger.info(
                    "incomplete %s OTP write status=%s (idle SUCCESS OK)",
                    label,
                    st,
                )
                after = shadow_map_word32(dut, MAP_BYTE_OFF)
                assert after is not None
                sb.expect_eq(
                    f"shadow unchanged after incomplete {label}",
                    after,
                    before,
                evidence="FEAT_PARTIAL_DENY")
                sb.expect_true(
                    f"incomplete {label} did not land pattern",
                    after != pat,
                )
            finally:
                release_forced(forced)

        # Contrast: full enable must land.
        forced_ok = force_feat_ctrl_bits(
            dut,
            {"fuse_test": 1, "soc_debug": 1, "ap_debug": 1},
            self.logger,
        )
        try:
            await ClockCycles(dut.clk_smu_i, 8)
            for _ in range(4):
                await jtag.step_tms(0)
            allow_pat = 0xA5A5_5A5A
            st_ok, _ = await otp_jtag2axi_single_write(
                jtag, SMC_EFUSE_MAP_BIRA_WORD, allow_pat
            )
            sb.expect_eq("full-enable OTP write status", st_ok, J2A_STATUS_SUCCESS)
            shadow = shadow_map_word32(dut, MAP_BYTE_OFF)
            assert shadow is not None
            sb.expect_eq("full-enable shadow == pattern", shadow, allow_pat)
        finally:
            release_forced(forced_ok)

        self.logger.info(
            "smu_feat_ctrl_partial_bit_corner_test: 3 incomplete denies + allow OK"
        )
