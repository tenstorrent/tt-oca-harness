# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""REGION_SIZE zero collapse, the power-of-two size sweep and the reset-based recovery."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_region_zero_reset_recovery_test_seq import (
    MIN_SEP_IN_ACCESSES,
    smc_region_zero_reset_recovery_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_region_zero_reset_recovery_test(smc_base_test):
    """Write REGION_SIZE 0 and every power of two, recovering each through a cold reset."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-REGION-SIZE-BELOW",
        "CHK-REGION-SIZE-BEYOND",
        "CHK-REGION-SIZE-READBACK",
        "CHK-REGION-SIZE-RECOVERY",
        "CHK-REGION-SIZE-SELF-DECERR",
        "CHK-REGION-SIZE-STRADDLE",
        "CHK-REGION-ZERO-DECERR",
        "CHK-REGION-ZERO-JTAG-OUTBOUND",
        "CHK-REGION-ZERO-RESET-RECOVERY",
        "CHK-RESET-MID-INBOUND",
        "CHK-RESET-MID-OUTBOUND",
        "CHK-RESET-RESTORES-WINDOW",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 14

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_region_zero_reset_recovery_test_seq("region_zero_reset_recovery_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.finished, "the sequence did not reach its last step"
        assert seq.accesses >= MIN_SEP_IN_ACCESSES, (
            f"only {seq.accesses} SEP_IN accesses issued, want >= {MIN_SEP_IN_ACCESSES}"
        )
