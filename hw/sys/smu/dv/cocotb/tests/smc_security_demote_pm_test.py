# SPDX-License-Identifier: Apache-2.0
"""smc_security_demote_pm_test - SEP=0 demote / lc_state observe-only.

Bare smu (SEP=0) ties lcc_demote_state_*_o to 0 and drives lc_state=0xf0.
Hierarchical Force of lc_state for sigint inject was removed (no-Force policy);
re-enable integrity inject when a legal TB pin exists (SMC-style) or under SEP=1
LCC.

Evidence kept (frontdoor observe):

  1. lcc_demote_state_1/2_o == 0 (SEP=0 tie-off)
  2. lc_state_o == 0xf0 and lc_sigint_err_o == 0 (good differential)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

SEP0_LC_STATE = 0xF0


@pyuvm.test()
class smc_security_demote_pm_test(smu_base_test):
    """SEP=0 demote outputs + default lc_state integrity (no Force)."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        sb.expect_eq(
            "SEP=0 lcc_demote_state_1_o",
            int(dut.lcc_demote_state_1_o.value) & 0x3,
            0,
            evidence="FEAT_FAB_DENY",
        )
        sb.expect_eq(
            "SEP=0 lcc_demote_state_2_o",
            int(dut.lcc_demote_state_2_o.value) & 0x3,
            0,
        )
        sb.expect_eq("SEP=0 lc_state_o", int(dut.lc_state_o.value) & 0xFF, SEP0_LC_STATE)
        sb.expect_eq("lc_sigint idle", int(dut.lc_sigint_err_o.value), 0)

        self.logger.info(
            "smc_security_demote_pm_test: demote tie-off + default lc OK "
            "(Force sigint inject deferred)"
        )
