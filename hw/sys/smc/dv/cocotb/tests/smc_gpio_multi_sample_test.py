# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM GPIO multi-sample test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_multi_sample_test_seq import smc_gpio_multi_sample_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_multi_sample_test(smc_base_test):
    """Run the SMC OSS GPIO multi-sample observability scenario."""

    required_evidence = (
        "CHK-GPIO-MULTI-SAMPLE-MATCHES-REF-1",
        "CHK-GPIO-MULTI-SAMPLE-MATCHES-REF-2",
        "CHK-GPIO-MULTI-SAMPLE-STABLE",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        seq = smc_gpio_multi_sample_test_seq("gpio_multi_sample_seq")
        await self.start_seq(seq, self.env.gpio_agent.sequencer)
