# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus slave replies shaped bit by bit: CRC acceptance, retry codes and buffered replies."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avsbus_slave_reply_test_seq import smc_avsbus_slave_reply_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_slave_reply_test(smc_base_test):
    """Answer the AVSBus controller's subframes with chosen replies on the sdata pad."""

    required_evidence = (
        "CHK-AVS-SLAVE-BUFFERED",
        "CHK-AVS-SLAVE-CRC-ONE-GOOD",
        "CHK-AVS-SLAVE-INTERRUPT",
        "CHK-AVS-SLAVE-INTERRUPT-LAUNCH",
        "CHK-AVS-SLAVE-MASKS",
        "CHK-AVS-SLAVE-NO-RETRY",
        "CHK-AVS-SLAVE-NUMERATOR",
        "CHK-AVS-SLAVE-RB-OVERFLOW",
        "CHK-AVS-SLAVE-READBACK",
        "CHK-AVS-SLAVE-RETRY-CODES",
        "CHK-AVS-SLAVE-STALL",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_slave_reply_test_seq("smc_avsbus_slave_reply_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
