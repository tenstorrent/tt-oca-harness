# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG-to-SYS_OUT path with responder control: route, split channels, recovery, stall."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sys_out_path_responder_control_test_seq import (
    smc_sys_out_path_responder_control_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sys_out_path_responder_control_test(smc_base_test):
    """Drive the SYS_OUT responder knobs behind JTAG accesses and local accesses."""

    required_evidence = (
        "CHK-TIMEOUT-PATHS",
        "CHK-JTAG-OUTBOUND-ROUTE",
        "CHK-JTAG-OUTBOUND-SILENT",
        "CHK-WSPLIT-AW-FIRST",
        "CHK-WSPLIT-W-FIRST",
        "CHK-WSPLIT-SAME-CYCLE",
        "CHK-OUT-READ-RECOVERY",
        "CHK-OUT-WRITE-RECOVERY",
        "CHK-STALLED-OUTBOUND-LOCAL-ANSWERED",
        "CHK-NONVAC",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sys_out_path_responder_control_test_seq("sys_out_path_responder_control_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses == 12, f"{seq.accesses} SEP_IN accesses issued, want 12"
