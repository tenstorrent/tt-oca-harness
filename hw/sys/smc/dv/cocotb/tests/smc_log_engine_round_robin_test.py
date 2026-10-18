# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine arbitration: whole messages, each exactly once, zero lengths skipped, LOG_LEN hold.

On wrapper 0: LOG_LEN written on four slots with two zero-length slots beside them, on all
sixteen slots, and on three slots followed by two more while a message is in flight, each wave
read back out of RBR in MCR.LOOP and decoded into messages.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_log_engine_round_robin_test_seq import smc_log_engine_round_robin_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_log_engine_round_robin_test(smc_base_test):
    """Message atomicity, exactly-once service and LOG_LEN hold and clear of wrapper 0."""

    required_evidence = (
        "CHK-LOGENG-LEN-HOLD-SUBMITTED",
        "CHK-LOGENG-LEN-HWCLEAR",
        "CHK-LOGENG-LEN-ZERO-NOT-PENDING",
        "CHK-LOGENG-RR-ATOMIC",
        "CHK-LOGENG-RR-EXACTLY-ONCE",
        "CHK-LOGENG-RR-IN-FLIGHT",
        "CHK-LOGENG-RR-ORDER-MEASURED",
        "CHK-LOGENG-RR-ZERO-SKIPPED",
        "CHK-NONVAC",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_round_robin_test_seq("smc_log_engine_round_robin_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
