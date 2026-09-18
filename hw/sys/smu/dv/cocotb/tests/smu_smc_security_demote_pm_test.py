# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_security_demote_pm_test - SEP=0 demote / lc_state observe-only.

Bare smu (SEP=0) ties lcc_demote_state_*_o to 0 and carries the no-LCC lifecycle
word of ``seq_lib.smu_lifecycle_table`` on lc_state_o.

Evidence kept (frontdoor observe):

  1. lcc_demote_state_1/2_o == 0 (SEP=0 hardwire observe across hold window)
  2. lc_state_o == the no-LCC word, stable (positive non-zero LC payload)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from seq_lib.smu_lifecycle_table import LC_STATE_NO_LCC
from smu_base_test import smu_base_test

HOLD_CYCLES = 16


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_smc_security_demote_pm_test(smu_base_test):
    """SEP=0 demote outputs + default lc_state observe."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()

        for cycle in range(HOLD_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            dem1 = _sample(dut.lcc_demote_state_1_o, "lcc_demote_state_1_o") & 0x3
            dem2 = _sample(dut.lcc_demote_state_2_o, "lcc_demote_state_2_o") & 0x3
            lc = _sample(dut.lc_state_o, "lc_state_o") & 0xFF
            if dem1 != 0:
                raise AssertionError(f"demote_1 mid-hold cycle={cycle} last={dem1}")
            if dem2 != 0:
                raise AssertionError(f"demote_2 mid-hold cycle={cycle} last={dem2}")
            if lc != LC_STATE_NO_LCC:
                raise AssertionError(f"lc_state mid-hold cycle={cycle} last=0x{lc:02x}")

        sb.expect_eq(
            "SEP=0 lcc_demote_state_1_o",
            _sample(dut.lcc_demote_state_1_o, "lcc_demote_state_1_o") & 0x3,
            0,
            evidence="DEMOTE_TIEOFF_OBS",
        )
        sb.expect_eq(
            "SEP=0 lcc_demote_state_2_o",
            _sample(dut.lcc_demote_state_2_o, "lcc_demote_state_2_o") & 0x3,
            0,
        )
        sb.expect_eq(
            "SEP=0 lc_state_o",
            _sample(dut.lc_state_o, "lc_state_o") & 0xFF,
            LC_STATE_NO_LCC,
        )

        self.logger.info(
            f"smu_smc_security_demote_pm_test: demote tie-off + lc_state=0x{LC_STATE_NO_LCC:02x} OK"
        )
