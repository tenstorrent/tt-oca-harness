# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded random AXI stress on SEP_IN, SYS_IN and JTAG toward the local fabric and output_axi."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axi_random_stress_test_seq import smc_axi_random_stress_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axi_random_stress_test(smc_base_test):
    """Random attributes, shapes, depths and SYS_OUT responder faults, golden by address."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-RAND-ATTR-OWN-WORD",
        "CHK-RAND-ID-ECHO",
        "CHK-RAND-LOCAL-DEEP",
        "CHK-RAND-LOCK-OBS",
        "CHK-RAND-OUT-DEEP",
        "CHK-RAND-OUT-OTHER-PORTS-DECERR",
        "CHK-RAND-OUT-SIDEBAND",
        "CHK-RAND-RESP-COMBINED",
        "CHK-RAND-RESP-ERRORS-ECHO",
        "CHK-RAND-RESP-TIMING",
        "CHK-RAND-SHAPE-BY-ADDR",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 13

    auto_protocol_vip = False
    sys_out_max_outstanding = 8

    async def run_scenario(self) -> None:
        seq = smc_axi_random_stress_test_seq("axi_random_stress_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
