# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_cdc_jitter_all_bridges_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test
from seq_lib.dtp_jtag2axi_cdc_jitter_test_seq import dtp_jtag2axi_cdc_jitter_test_seq


@pyuvm.test()
class dtp_jtag2axi_cdc_jitter_all_bridges_test(dtp_jtag2axi_robustness_base_test):
    """Writes land and a series read discarded by a system reset recovers under CDC jitter.

    The testlist entry arms the jitter model with
    ``+cdc_instrumentation_enabled=1``.
    """

    scenario = "cdc_jitter_all_bridges"
    specific_knob = "DTP_JTAG2AXI_CDC_JITTER_ALL_BRIDGES_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-J2A-MEM-IMAGE",
        "CHK-J2A-STATUS-BIT",
        "CHK-RESET-COUNT",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-SERIES-ADDR",
        "CHK-J2A-CDC-CLEAR",
        "CHK-J2A-ABORT-FSM",
        "CHK-J2A-ABORT-ESCAPE",
        "CHK-J2A-ABORT-RECOVERY",
    )

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_cdc_jitter_test_seq,
            self.scenario,
            specific_knob=self.specific_knob,
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario=self.scenario,
        )
