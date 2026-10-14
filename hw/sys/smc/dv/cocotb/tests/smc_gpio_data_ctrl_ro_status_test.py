# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO DATA_CTRL hardware-status bits written from software.

Sources hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL, DATA_CTRL_ENABLE).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_data_ctrl_ro_status_test_seq import (
    smc_gpio_data_ctrl_ro_status_test_seq,
)
from smc_base_test import smc_base_test

# Expected CSR access floor, independent of the sequence count:
#   65 DATA_CTRL scan reads                                                     65
#   2 (lsio write, read back)                                                    2
#   10 (idle enable read, bit 31 write, read, rx on write, enable set, read, rx read,
#       enable clear, rx off write, read)                                       10
#   7 (all ones, read, zeros, read, restore, read, enable read)                  7
GPIO_DATA_CTRL_RO_STATUS_MIN_CSR_ACCESSES = 65 + 2 + 10 + 7


@pyuvm.test()
class smc_gpio_data_ctrl_ro_status_test(smc_base_test):
    """Write the sw=r hw=w DATA_CTRL bits of one GPIO instance and read them back."""

    required_evidence = (
        "CHK-GPIO-DATA-CTRL-LSIO-ENABLE-RO",
        "CHK-GPIO-DATA-CTRL-PAD2CORE-RO",
        "CHK-GPIO-DATA-CTRL-WRITE-ALL-ONES",
        "CHK-NONVAC",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_data_ctrl_ro_status_test_seq("smc_gpio_data_ctrl_ro_status_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            min_csr_accesses=GPIO_DATA_CTRL_RO_STATUS_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details="DATA_CTRL bits 25 and 31 written on instance 60",
        )
