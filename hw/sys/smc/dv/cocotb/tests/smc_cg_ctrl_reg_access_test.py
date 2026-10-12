# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLOCK_GATE_CONTROL register access over SEP_IN.

Contract SMC_CLOCK_GATE_012, anchor smc_cg_ctrl_reg_access_test.
Scenarios GATE-CGC-REG.S1..S7 at the default clock triple.
Sources: hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cg_ctrl_reg_access_test_seq import smc_cg_ctrl_reg_access_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cg_ctrl_reg_access_test(smc_base_test):
    """CLOCK_GATE_CONTROL reset value, walking enables, hysteresis, reserved, narrow, rewrite."""

    required_evidence = (
        "CHK-CGC-RESET-VALUE",
        "CHK-CGC-WALKING-ONE",
        "CHK-CGC-WALKING-ZERO",
        "CHK-CGC-HYST-RANGE",
        "CHK-CGC-RESERVED-BITS",
        "CHK-CGC-NARROW-ACCESS",
        "CHK-CGC-REWRITE",
        "CHK-NONVAC",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cg_ctrl_reg_access_test_seq("cg_ctrl_reg_access_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
