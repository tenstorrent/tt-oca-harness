# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM GPIO multi-sample test."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_gpio_multi_sample_test_seq import smc_gpio_multi_sample_test_seq


@pyuvm.test()
class smc_gpio_multi_sample_test(smc_base_test):
    """Run the SMC OSS GPIO multi-sample observability scenario."""

    async def run_scenario(self) -> None:
        seq = smc_gpio_multi_sample_test_seq("gpio_multi_sample_seq")
        await self.start_seq(seq, self.env.gpio_agent.sequencer)
