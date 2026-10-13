# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO_INTF reset-word write-back on all 65 instances.

Contract SMC_GPIO_CSR_011, anchor smc_gpio_intf_reset_writeback_test.
Allocated scenarios: GPIO-CSR-RESET.S5.
Spec sources: hw/ip/gpio/regs/gpio_intf.rdl, hw/sys/smc/regs/gen/c/smc_addr.h.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_intf_reset_writeback_test_seq import smc_gpio_intf_reset_writeback_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_intf_reset_writeback_test(smc_base_test):
    """Write the reset words to ACCESS_FILTER, DATA_CTRL_ENABLE and DATA_CTRL and read back."""

    required_evidence = ("CHK-GPIO-RESET-WRITEBACK", "CHK-NONVAC")
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_intf_reset_writeback_test_seq("smc_gpio_intf_reset_writeback_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
