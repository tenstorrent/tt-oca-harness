# SPDX-License-Identifier: Apache-2.0
"""smc_security_demote_pm_test - SEP=0 demote tie-off + lc_state sigint.

Bare smu (SEP=0) ties lcc_demote_state_*_o to 0 and drives lc_state=0xf0.
Demote/PM firmware path is wrapper-only; this OSS probe checks:

  1. lcc_demote_state_1/2_o == 0 (SEP=0 tie-off)
  2. lc_state_o == 0xf0 and lc_sigint_err_o == 0 (good differential)
  3. Force bad lc_state encoding -> lc_sigint_err_o rises
  4. Restore good encoding -> lc_sigint_err_o clears
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

SEP0_LC_STATE = 0xF0
# Differential bad: both nibbles equal (integrity fail)
BAD_LC_STATE = 0x11
# PROD differential: {~1, 1} = 0xE1
PROD_LC_STATE = 0xE1

_LC_FORCE_CANDIDATES = (
    "u_dut.sep_lc_state",
    "u_dut.u_smc.lc_state_i",
)


def _resolve(dut, path: str):
    node = dut
    for part in path.split("."):
        if not hasattr(node, part):
            return None
        node = getattr(node, part)
    return node


@pyuvm.test()
class smc_security_demote_pm_test(smu_base_test):
    """SEP=0 demote outputs + lc_state differential integrity."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        sb.expect_eq(
            "SEP=0 lcc_demote_state_1_o", int(dut.lcc_demote_state_1_o.value) & 0x3, 0
        , evidence="FEAT_FAB_DENY")
        sb.expect_eq(
            "SEP=0 lcc_demote_state_2_o", int(dut.lcc_demote_state_2_o.value) & 0x3, 0
        )
        sb.expect_eq("SEP=0 lc_state_o", int(dut.lc_state_o.value) & 0xFF, SEP0_LC_STATE)
        sb.expect_eq("lc_sigint idle", int(dut.lc_sigint_err_o.value), 0)

        lc_handle = None
        for path in _LC_FORCE_CANDIDATES:
            lc_handle = _resolve(dut, path)
            if lc_handle is not None:
                self.logger.info("Forcing LC via %s", path)
                break
        # Precondition guard, not a scoreboard check: resolving a Force target
        # is test-setup, not RTL evidence. The real evidence is the
        # lc_sigint_err_o expect_eq below.
        assert lc_handle is not None, "no lc_state Force target resolved"

        try:
            lc_handle.value = Force(BAD_LC_STATE)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                "bad lc_state raises lc_sigint_err_o",
                int(dut.lc_sigint_err_o.value),
                1,
            )

            lc_handle.value = Force(PROD_LC_STATE)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                "good PROD lc_state clears lc_sigint_err_o",
                int(dut.lc_sigint_err_o.value),
                0,
            )
            sb.expect_eq(
                "Forced PROD visible on lc_state_o",
                int(dut.lc_state_o.value) & 0xFF,
                PROD_LC_STATE,
            )
        finally:
            try:
                lc_handle.value = Release()
            except Exception:
                pass

        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "lc_state restored to SEP=0 default",
            int(dut.lc_state_o.value) & 0xFF,
            SEP0_LC_STATE,
        )

        self.logger.info("smc_security_demote_pm_test: demote tie-off + lc sigint OK")
