# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A forced AVSBus slave resync from idle, mid-frame, with a queue and twice.

Contract SMC_POWER_AVS_011, anchor smc_avsbus_resync_force_test.
Scenarios: AVS-RESYNC.S6, AVS-RESYNC.S7, AVS-RESYNC.S8, AVS-RESYNC.S9, INT-AVS-RESYNC-INFLIGHT.
Sources: hw/ip/avsbus_controller/doc/architecture.adoc, regs/avsbus_controller.rdl.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avsbus_resync_force_test_seq import smc_avsbus_resync_force_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_resync_force_test(smc_base_test):
    """Force the slave resync four ways and follow the FSM probe and the master subframes."""

    required_evidence = (
        "CHK-AVS-FORCE-ONE-RESYNC",
        "CHK-AVS-FORCE-FRAME-COMPLETES",
        "CHK-AVS-FORCE-INFLIGHT-INT",
        "CHK-AVS-FORCE-QUEUE-ORDER",
        "CHK-AVS-FORCE-TWICE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_resync_force_test_seq("smc_avsbus_resync_force_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
