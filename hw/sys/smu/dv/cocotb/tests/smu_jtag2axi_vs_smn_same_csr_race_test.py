# SPDX-License-Identifier: Apache-2.0
"""smu_jtag2axi_vs_smn_same_csr_race_test - P3-H3a JTAG2AXI || SMN race (G4).

Program SYS_IN window over SCRATCH, then race two managers on the same CSR:

  1. Concurrent JTAG2AXI write PAT_J and SMN write PAT_S
  2. After both complete: final value is one of {PAT_J, PAT_S} (no tear)
  3. SMN and JTAG2AXI readbacks agree with each other and with final
  4. VERSION_LO still SUCCESS/OKAY (bridge not stuck)

Must FAIL if lost update / silent tear / agents disagree after settle.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import (
    axi_read32_resp,
    axi_write32_resp,
    make_smu_axi_master,
)
from seq_lib.smu_filter_helpers import (
    SCRATCH_COLD_ADDR,
    SMC_VERSION_LO_ADDR,
    VERSION_LO_EXPECT,
    program_inbound0_window,
)
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

PAT_J = 0x17A6_0001
PAT_S = 0x5A11_0002
WINDOW_START = 0xC000_2800
WINDOW_END = 0xC000_2908


@pyuvm.test()
class smu_jtag2axi_vs_smn_same_csr_race_test(smu_base_test):
    """Race JTAG2AXI vs SMN on SCRATCH; coherent winner, no tear."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        winner = 0
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            await program_inbound0_window(
                jtag,
                WINDOW_START,
                WINDOW_END,
                scoreboard=sb,
                tag="H3a",
            )

            st0, _ = await jtag2axi_single_write(
                jtag,
                SCRATCH_COLD_ADDR,
                0x0,
                wstrb=0xF,
                size=SMC_DBG_AXSIZE_4B,
            )
            sb.expect_eq("pre-race scratch clear", st0, J2A_STATUS_SUCCESS)

            j_result: dict = {}
            s_result: dict = {}

            async def _jtag_writer():
                st, _ = await jtag2axi_single_write(
                    jtag,
                    SCRATCH_COLD_ADDR,
                    PAT_J,
                    wstrb=0xF,
                    size=SMC_DBG_AXSIZE_4B,
                )
                j_result["st"] = st

            async def _smn_writer():
                resp = await axi_write32_resp(master, SCRATCH_COLD_ADDR, PAT_S)
                s_result["resp"] = resp

            t_j = cocotb.start_soon(_jtag_writer())
            t_s = cocotb.start_soon(_smn_writer())
            await t_j
            await t_s

            sb.expect_eq("race JTAG write status", j_result["st"], J2A_STATUS_SUCCESS)
            sb.expect_eq("race SMN write resp", s_result["resp"], AxiResp.OKAY)

            await ClockCycles(dut.clk_smu_i, 64)

            st_r, jdata = await jtag2axi_single_read(
                jtag, SCRATCH_COLD_ADDR, size=SMC_DBG_AXSIZE_4B
            )
            sb.expect_eq("post-race JTAG read status", st_r, J2A_STATUS_SUCCESS)
            j_val = int(jdata) & 0xFFFF_FFFF

            s_val, s_resp = await axi_read32_resp(master, SCRATCH_COLD_ADDR)
            sb.expect_eq("post-race SMN read resp", s_resp, AxiResp.OKAY)
            s_val = int(s_val) & 0xFFFF_FFFF

            sb.expect_eq("post-race JTAG==SMN readback", j_val, s_val)
            sb.expect_true(
                f"post-race value is a race winner (got 0x{j_val:08x})",
                j_val in (PAT_J, PAT_S),
            )
            winner = j_val

            st_v, r_v = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("post-race VERSION_LO status", st_v, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "post-race VERSION_LO data",
                int(r_v) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
            v_smn, v_resp = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
            sb.expect_eq("post-race SMN VERSION OKAY", v_resp, AxiResp.OKAY)
            sb.expect_eq(
                "post-race SMN VERSION data",
                int(v_smn) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_jtag2axi_vs_smn_same_csr_race_test: winner=0x%08x OK", winner
        )
