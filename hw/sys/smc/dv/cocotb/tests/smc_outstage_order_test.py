# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound stage order: alias remap, output remap, outbound filter, output_axi."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_outstage_order_test_seq import MIN_SEP_IN_ACCESSES, smc_outstage_order_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_outstage_order_test(smc_base_test):
    """JTAG and DMA traffic through the outbound stages, and a cold reset with a write in flight."""

    required_evidence = (
        "CHK-STAGE-FILTER-POST-REMAP",
        "CHK-INT-REMAP-FILTER",
        "CHK-STAGE-ALIAS-THEN-OUTPUT",
        "CHK-STAGE-BLOCKED-NOTHING-ON-OUTPUT",
        "CHK-STAGE-SIMULTANEOUS",
        "CHK-STAGE-SECOND-WHILE-PENDING",
        "CHK-STAGE-RESET-IN-FLIGHT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outstage_order_test_seq("outstage_order_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.finished, "the sequence did not reach its cleanup step"
        assert seq.accesses >= MIN_SEP_IN_ACCESSES, (
            f"only {seq.accesses} SEP_IN accesses issued, want >= {MIN_SEP_IN_ACCESSES}"
        )
