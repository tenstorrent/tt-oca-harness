# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO DATA_CTRL field values, read-modify-write isolation and Programmer's Guide constants.

Sources hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL), doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_data_ctrl_rw_values_test_seq import (
    smc_gpio_data_ctrl_rw_values_test_seq,
)
from smc_base_test import smc_base_test

# Expected CSR access floor, independent of the sequence count:
#   1 idle read                                                            1
#   4 enable_rx_tx values x (write, read) + restore, read                  10
#   4 interrupt_type values x (write, read) + restore, read                10
#   preset (write, read) + 7 fields x (read, write, read) + restore, read  25
#   6 constants x (write, read, restore, read)                             24
GPIO_DATA_CTRL_RW_VALUES_MIN_CSR_ACCESSES = 1 + 10 + 10 + 25 + 24


@pyuvm.test()
class smc_gpio_data_ctrl_rw_values_test(smc_base_test):
    """Drive DATA_CTRL field values and read-modify-writes on one idle GPIO instance."""

    required_evidence = (
        "CHK-GPIO-DATA-CTRL-INTERRUPT-TYPE-VALUES",
        "CHK-GPIO-DATA-CTRL-PG-CONSTANTS",
        "CHK-GPIO-DATA-CTRL-RMW-ISOLATION",
        "CHK-GPIO-DATA-CTRL-RX-TX-VALUES",
        "CHK-NONVAC",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_data_ctrl_rw_values_test_seq("smc_gpio_data_ctrl_rw_values_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            min_csr_accesses=GPIO_DATA_CTRL_RW_VALUES_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details="DATA_CTRL field values, read-modify-writes and constants on instance 60",
        )
