# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO DATA_CTRL_ENABLE single-bit writes and DATA_CTRL cross-register isolation.

Contract SMC_GPIO_CSR_010, anchor smc_gpio_data_ctrl_enable_fields_test.
Scenarios GPIO-CSR-DATA-CTRL-ENABLE.S1 and GPIO-CSR-DATA-CTRL-ENABLE.S3.
Sources hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL_ENABLE, DATA_CTRL).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_data_ctrl_enable_fields_test_seq import (
    smc_gpio_data_ctrl_enable_fields_test_seq,
)
from smc_base_test import smc_base_test

# Written out here rather than read from `seq.accesses`.
#   2 idle reads                                                          2
#   3 bits x (set, read back, restore, read back)                        12
#   2 orders x (2 writes, 2 reads, 2 final reads, 2 restores, 2 reads)  20
GPIO_DATA_CTRL_ENABLE_MIN_CSR_ACCESSES = 2 + 3 * 4 + 2 * 10 + 2


@pyuvm.test()
class smc_gpio_data_ctrl_enable_fields_test(smc_base_test):
    """Drive DATA_CTRL_ENABLE bits alone and against DATA_CTRL on one idle GPIO instance."""

    required_evidence = (
        "CHK-GPIO-ENABLE-BITS-ALONE",
        "CHK-GPIO-ENABLE-CROSS-REGISTER",
        "CHK-NONVAC",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_data_ctrl_enable_fields_test_seq("smc_gpio_data_ctrl_enable_fields_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            min_csr_accesses=GPIO_DATA_CTRL_ENABLE_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{seq.bits_driven} DATA_CTRL_ENABLE bits, {seq.orders_driven} orders",
        )
