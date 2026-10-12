# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stalled R, W and B handshakes on UART SCR and SCRATCH at ref / smc / periph 10 / 1.25 / 5 ns.

Contract SMC_CLOCK_RATIO_012, anchor smc_clk_ratio_handshake_stall_test.
Allocated scenarios: RATIO-HANDSHAKE-STALL.S1, RATIO-HANDSHAKE-STALL.S2, RATIO-HANDSHAKE-STALL.S3.
Spec sources: hw/sys/smc/doc/fabric.adoc, hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clk_ratio_handshake_stall_test_seq import (
    smc_clk_ratio_handshake_stall_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-STALL-PERIPH-READ",
    "CHK-STALL-PERIPH-WRITE",
    "CHK-STALL-SMC",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_clk_ratio_handshake_stall_test(smc_base_test):
    """Stalled reads and trailing-data writes on UART SCR[0] and SCRATCH[0]."""

    required_evidence = REQUIRED
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clk_ratio_handshake_stall_test_seq("clk_ratio_handshake_stall_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n != "CHK-NONVAC" and n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
