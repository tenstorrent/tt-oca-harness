# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM GPIO observe test.

Samples the OR-of-vector GPIO observability outputs exposed at tb_top. With
no CSR programming, all three should read 0 after cold-reset release.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_observe_test_seq import smc_gpio_observe_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_observe_test(smc_base_test):
    async def run_scenario(self) -> None:
        seq = smc_gpio_observe_test_seq("gpio_observe_seq")
        await self.start_seq(seq, self.env.gpio_agent.sequencer)
