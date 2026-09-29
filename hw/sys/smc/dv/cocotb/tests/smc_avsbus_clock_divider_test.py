# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus clock divider settings reaching the clock the block drives.

The divisor and the duty-cycle numerator are compared separately by the
divider, so each is written on its own and the AVS clock at the pad is
measured against the setting that was written.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avsbus_clock_divider_test_seq import smc_avsbus_clock_divider_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_clock_divider_test(smc_base_test):
    """A written AVSBus divider setting must reach the clock at the pad."""

    required_evidence = (
        "CHK-AVS-CLKDIV-DUTY",
        "CHK-AVS-CLKDIV-MINIMUM",
        "CHK-AVS-CLKDIV-PERIOD",
        "CHK-AVS-CLKDIV-RESTORE",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_clock_divider_test_seq("avsbus_clock_divider_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
