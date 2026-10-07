# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_robustness_test_seq import dtp_jtag2axi_robustness_test_seq


@pyuvm.test()
class dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test(dtp_base_test):
    """Run the `cdc_clear_abort_narrow_reset_mid_xaction` JTAG2AXI scenario on every bridge."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-RESET-COUNT",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-ABORT-MIDFLIGHT",
        "CHK-J2A-ABORT-FSM",
        "CHK-J2A-CDC-CLEAR",
        "CHK-J2A-ABORT-ESCAPE",
        "CHK-J2A-ABORT-RECOVERY",
        "CHK-J2A-ORPHAN-DRAIN",
        "CHK-J2A-ORPHAN-DISCARD",
        "CHK-J2A-ORPHAN-ORDER",
    )
    axi_checker_stream_minimums = {"smc_axi": 2, "smc_otp": 2, "sep_otp": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_robustness_test_seq,
            "cdc_clear_abort_narrow_reset_mid_xaction",
            specific_knob="DTP_JTAG2AXI_CDC_CLEAR_ABORT_NARROW_RESET_MID_XACTION_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="cdc_clear_abort_narrow_reset_mid_xaction",
        )
