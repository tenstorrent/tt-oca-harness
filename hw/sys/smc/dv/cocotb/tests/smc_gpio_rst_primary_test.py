# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO primary-reset effect on interrupt state and on an in-flight access."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_gpio_rst_primary_test_seq import smc_gpio_rst_primary_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_rst_primary_test(smc_base_test):
    """A cold reset clears a wrap's interrupt state and bounds an in-flight access."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-RST-PRIMARY-AXI-BOUNDED",
        "CHK-RST-PRIMARY-EDGE",
        "CHK-RST-PRIMARY-LEVEL-IRQ",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_rst_primary_test_seq("gpio_rst_primary_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
