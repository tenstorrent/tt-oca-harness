# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base of the cross-bridge JTAG2AXI robustness tests.

The SV-UVM twin is ``uvm/tests/dtp_jtag2axi_robustness_base_test.svh``.
"""

from __future__ import annotations

from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_robustness_test_seq import dtp_jtag2axi_robustness_test_seq


class dtp_jtag2axi_robustness_base_test(dtp_base_test):
    """Cross-bridge robustness scenario test.

    Every bridge's stream must compare at least two transactions, so a silent
    bridge fails at finalization. A concrete test names its ``scenario``, its
    ``specific_knob``, and the evidence IDs it requires.
    """

    use_axi_scoreboard = True
    axi_checker_stream_minimums = {"smc_axi": 2, "smc_otp": 2, "sep_otp": 2}
    scenario: str = ""
    specific_knob: str = ""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_robustness_test_seq,
            self.scenario,
            specific_knob=self.specific_knob,
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario=self.scenario,
        )
