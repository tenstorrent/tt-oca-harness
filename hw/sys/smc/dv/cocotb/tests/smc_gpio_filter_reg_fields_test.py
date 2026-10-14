# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO ACCESS_FILTER requirement value space and individual enable bit set and clear.

Sources hw/ip/gpio/regs/gpio_intf.rdl (ACCESS_FILTER).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_filter_reg_fields_test_seq import smc_gpio_filter_reg_fields_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_filter_reg_fields_test(smc_base_test):
    """Drive ACCESS_FILTER fields on one idle GPIO instance."""

    required_evidence = (
        "CHK-GPIO-FILTER-REG-ENABLE-BITS",
        "CHK-GPIO-FILTER-REG-REQ-VALUES",
        "CHK-NONVAC",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_filter_reg_fields_test_seq("smc_gpio_filter_reg_fields_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
