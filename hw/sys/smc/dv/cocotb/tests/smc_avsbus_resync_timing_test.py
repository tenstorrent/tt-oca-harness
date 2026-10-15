# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus slave resync after a cold reset: length, interval, status flags and the FSM probe.

Sources: hw/ip/avsbus_controller/doc/{architecture,interface}.adoc, regs/avsbus_controller.rdl.
"""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_avsbus_resync_timing_test_seq import smc_avsbus_resync_timing_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_resync_timing_test(smc_base_test):
    """Follow the resync after a cold reset, its length, flags and interval on the FSM probe."""

    required_evidence = (
        "CHK-AVS-FSM-IDLE-FLAG",
        "CHK-AVS-FSM-ONEHOT",
        "CHK-AVS-FSM-RESET-SEQUENCE",
        "CHK-AVS-RESYNC-FLAG",
        "CHK-AVS-RESYNC-INTERVAL",
        "CHK-AVS-RESYNC-INTERVAL-ZERO",
        "CHK-AVS-RESYNC-LEN35",
        "CHK-AVS-RESYNC-PIN-HIGH",
        "CHK-AVS-RESYNC-REWRITE",
        "CHK-AVS-RESYNC-STARTUP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_resync_timing_test_seq("smc_avsbus_resync_timing_test_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
