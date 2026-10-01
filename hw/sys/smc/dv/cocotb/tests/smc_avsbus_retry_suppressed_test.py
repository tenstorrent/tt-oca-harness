# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus retry budget of 0: the failing reply is kept, not resent.

AVS_CFG_0.MAX_RETRIES = 0 tells the controller to suppress retries, so an
unanswered command reports the failure and pushes the reply to the readback
FIFO instead of resending it. The same stimulus with a budget of 1 is the
positive control for the absences the suppressed leg measures.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avsbus_retry_suppressed_test_seq import smc_avsbus_retry_suppressed_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_retry_suppressed_test(smc_base_test):
    """A retry budget of 0 must answer the failure without resending."""

    required_evidence = (
        "CHK-AVS-RETRY-SUPPRESSED",
        "CHK-AVS-RETRY-SUPPRESSED-CONTROL",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_retry_suppressed_test_seq("avsbus_retry_suppressed_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
