# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I3C window response across the peripheral clock gate over SEP_IN AXI.

Sources: smc_base_config.rdl CLOCK_GATE_CONTROL.i3c_cg_en, clk_rst.adoc, memmap.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i3c_clock_gate_window_test_seq import smc_i3c_clock_gate_window_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_clock_gate_window_test(smc_base_test):
    """Set and clear i3c_cg_en and check the six I3C windows answer SLVERR or OKAY."""

    required_evidence = (
        "CHK-I3C-GATE-FIRST-ACCESS-BOUND",
        "CHK-I3C-GATE-IDEMPOTENT",
        "CHK-I3C-GATE-INFLIGHT-GROUPS",
        "CHK-I3C-GATE-OTHER-WINDOWS",
        "CHK-I3C-GATE-POST-WRITE-SLVERR",
        "CHK-I3C-GATE-RESTORE-DECODE",
        "CHK-I3C-GATED-SLVERR",
        "CHK-I3C-GATED-WRITE-RETAINED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_clock_gate_window_test_seq("smc_i3c_clock_gate_window_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
