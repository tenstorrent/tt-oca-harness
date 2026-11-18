# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cycle counts of the reset controller and the pins that follow a reset without a synchroniser.

Spec: clk_rst.adoc (SMC Reset Unit, Power-Good and Cold Reset, SMC Reset Distribution).
"""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_reset_timing_bounds_test_seq import (
    CHK_EXTENSION,
    CHK_GPIO,
    CHK_SS,
    CHK_STRETCH,
    smc_reset_timing_bounds_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_timing_bounds_test(smc_base_test):
    """Cold extension, powergood stretch, pad enables in cold, unsynchronised subsystem pins."""

    required_evidence = (CHK_EXTENSION, CHK_GPIO, CHK_STRETCH, CHK_SS)
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_timing_bounds_test_seq("smc_reset_timing_bounds_test_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.passes == [CHK_GPIO, CHK_EXTENSION, CHK_STRETCH, CHK_SS], (
            f"legs that passed: {seq.passes}"
        )
