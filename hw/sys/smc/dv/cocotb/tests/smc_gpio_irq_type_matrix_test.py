# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS GPIO interrupt-type (active-high / active-low level) matrix test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_irq_type_matrix_test_seq import (
    smc_gpio_irq_type_matrix_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_irq_type_matrix_test(smc_base_test):
    """Drive GPIO0 for both level polarities and check the IRQ aggregate."""

    required_evidence = ("CHK-GPIO-IRQ-TYPE-POLARITY",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_irq_type_matrix_test_seq("gpio_irq_type_matrix_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
