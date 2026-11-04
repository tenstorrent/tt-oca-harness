# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The 62/3 GPIO default direction map at the pads, in operation and under a cold reset."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_gpio_default_direction_test_seq import smc_gpio_default_direction_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_default_direction_test(smc_base_test):
    """INPUT_BY_DEFAULT per instance on the pad vectors, forced by rst_cold_ni on all 65."""

    required_evidence = ("CHK-GPIO-DEFAULT-DIRECTION-MAP",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_default_direction_test_seq("smc_gpio_default_direction_test_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
