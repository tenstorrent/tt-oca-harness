# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Three-port by two-base reachability matrix of the SMC window.

Contract XBAR_022, anchor smc_inbound_window_port_matrix_test.
Allocated scenarios: XBAR-WIN-LOCAL.S1/S3, XBAR-WIN-GLOBAL.S1/S2, XBAR-JTAG-LOCAL.S1/S2,
XBAR-SYS-DEMUX.S1, XBAR-SEP-DEMUX.S1, INT-LOCAL-GLOBAL-REBASE.
Spec sources: fabric.adoc Fabric Topology and Alias Remapping, memmap.adoc Memory Map,
smc_base_config.rdl resets.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_inbound_window_port_matrix_test_seq import (
    STIMULUS_FLOOR,
    smc_inbound_window_port_matrix_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_inbound_window_port_matrix_test(smc_base_test):
    """Base registers, window words and scratch storage on sep, sys and jtag at both bases."""

    required_evidence = (
        "CHK-WIN-LOCAL-BASEREG-PORTS",
        "CHK-WIN-LOCAL-REGS-PORTS",
        "CHK-WIN-GLOBAL-RESET-PORTS",
        "CHK-SYS-SEP-WINDOW-WORDS",
        "CHK-WIN-CROSS-BASE-STORAGE",
        "CHK-JTAG-LOCAL-WINDOW",
        "CHK-JTAG-CROSS-PORT-STORAGE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_inbound_window_port_matrix_test_seq("inbound_window_port_matrix_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "INBOUND_WINDOW_PORT_MATRIX")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
