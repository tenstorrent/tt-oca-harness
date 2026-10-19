# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine slot start, capacity clamp, zero capacity and resubmission over region sizes.

On wrapper 0: LOG_REGION_SIZE 0x80 over all sixteen slots, 0x200 over three slots and a
resubmission, the sizes 135, 143, 144 and 271 with lengths at, above and far above the capacity,
the zero-capacity size 127, and lengths 9 and 7 as a measured leg, each message read back out of
RBR in MCR.LOOP.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_log_engine_region_size_test_seq import smc_log_engine_region_size_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_log_engine_region_size_test(smc_base_test):
    """Slot start, capacity clamp, zero capacity and resubmission of the wrapper 0 engine."""

    required_evidence = (
        "CHK-LOGENG-REGION-BYTE-ORDER",
        "CHK-LOGENG-REGION-LEN-NOT-MULT8-MEASURED",
        "CHK-LOGENG-REGION-RESUBMIT",
        "CHK-LOGENG-REGION-SLOT-START-MID",
        "CHK-LOGENG-REGION-SLOT-START-MIN",
        "CHK-LOGENG-REGION-UNALIGNED-BELOW-CAP",
        "CHK-LOGENG-REGION-UNALIGNED-CAPACITY",
        "CHK-LOGENG-REGION-UNALIGNED-START-MEASURED",
        "CHK-LOGENG-REGION-ZERO-CAPACITY",
        "CHK-NONVAC",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_region_size_test_seq("smc_log_engine_region_size_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
