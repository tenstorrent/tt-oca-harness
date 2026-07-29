# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_otp_sep0_err_slv_test - P2-I2b SEP=0 SEP-OTP err_slv (real checkers).

RTL fact (SEP=0): JTAG_SEP_DBG_ENABLE=0 -> gen_no_sep_otp_jtag2axi ties
axil_sep_otp_jtag_req_o to 0 (no SEP OTP JTAG2AXI bridge). gen_no_sep still
instantiates u_sep_otp_axil_err_slv with RESP_DECERR / RESP_DATA=0xBADCAB1E.

Evidence (must FAIL if err_slv silent or SMC OTP contrast broken):

  1. Frontdoor: during SEP OTP IR activity, dtp_axil_sep_otp_jtag_req stays idle
  2. Hierarchical AXIL into err_slv: DECERR + poison 0xBADCAB1E
  3. Contrast: ungated SMC OTP MAP read SUCCESS (path still live)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_axil_hier_helpers import axil_hier_read32, axil_req_get
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_EFUSE_MAP_BIRA_WORD,
    force_otp_jtag2axi_lifecycle_enable,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    release_forced,
    sep_otp_jtag2axi_single_read,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

ERR_SLV_POISON = 0xBADC_AB1E
AXI_DECERR = 3
PROBE_ADDR = 0x0000_0080


async def _count_sep_otp_ar_aw(dut, cycles: int = 200) -> tuple[int, int]:
    aw = ar = 0
    req = dut.u_dut.dtp_axil_sep_otp_jtag_req
    for _ in range(cycles):
        await RisingEdge(dut.clk_ref_i)
        if axil_req_get(req, "aw_valid"):
            aw += 1
        if axil_req_get(req, "ar_valid"):
            ar += 1
    return aw, ar


@pyuvm.test()
class smu_dtp_otp_sep0_err_slv_test(smu_base_test):
    """SEP=0 SEP-OTP err_slv DECERR/poison + SMC OTP contrast."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        # 1) Frontdoor SEP OTP IR must not drive the tied-off AXIL manager.
        mon = cocotb.start_soon(_count_sep_otp_ar_aw(dut, 300))
        st_sep, _ = await sep_otp_jtag2axi_single_read(jtag, PROBE_ADDR, poll_limit=16)
        aw_n, ar_n = await mon
        self.logger.info("SEP OTP frontdoor status=%s (bridge absent)", st_sep)
        sb.expect_eq("SEP OTP AXIL AW idle during frontdoor IR", aw_n, 0, evidence="OTP_SEP0_ERR_SLV")
        sb.expect_eq("SEP OTP AXIL AR idle during frontdoor IR", ar_n, 0)

        # 2) Hierarchical probe of gen_no_sep err_slv (clk_ref domain).
        req = dut.u_dut.dtp_axil_sep_otp_jtag_req
        resp = dut.u_dut.dtp_axil_sep_otp_jtag_resp
        rresp, rdata = await axil_hier_read32(
            dut.clk_ref_i, req, resp, PROBE_ADDR
        )
        sb.expect_eq("SEP OTP err_slv RRESP DECERR", rresp, AXI_DECERR)
        sb.expect_eq(
            "SEP OTP err_slv poison",
            int(rdata) & 0xFFFF_FFFF,
            ERR_SLV_POISON,
        )

        # 3) Contrast: SMC OTP path still completes into MAP.
        otp_en = force_otp_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)
            st_smc, _ = await otp_jtag2axi_single_read(jtag, SMC_EFUSE_MAP_BIRA_WORD)
            sb.expect_eq("SMC OTP MAP contrast SUCCESS", st_smc, J2A_STATUS_SUCCESS)
        finally:
            release_forced(otp_en)

        self.logger.info("smu_dtp_otp_sep0_err_slv_test: err_slv + contrast OK")
