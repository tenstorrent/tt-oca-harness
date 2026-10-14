# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS GPIO/IRQ CSR precheck."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_irq_active_test_seq import smc_gpio_irq_active_test_seq
from seq_lib.smc_gpio_vip_utils import check_gpio0_active_low_irq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_irq_active_test(smc_base_test):
    """Run GPIO CSR plus IRQ-control decode precheck."""

    required_evidence = (
        "CHK-GPIO-IRQ-ACTIVE-LOW",
        "CHK-GPIO-IRQ-ACTIVE-LOW-ASSERT",
        "CHK-GPIO-IRQ-ACTIVE-LOW-CLEAR",
        "CHK-GPIO-IRQ-ACTIVE-LOW-IDLE",
        "CHK-GPIO0-DATA-CTRL-READBACK",
        "CHK-MAILBOX-IRQEN-RESET",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_irq_active_test_seq("gpio_irq_active_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_gpio0_active_low_irq()
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            csr_accesses=seq.accesses,
            # Fail-capable stimulus floor: the GPIO0 DATA_CTRL active-low-IRQ
            # write plus the MAILBOX_IRQEN decode read (smc_gpio_irq_active_test_seq,
            # directed, no polling); a floor taken from `seq.accesses` would
            # shrink with a sequence that stopped issuing them.
            min_csr_accesses=2,
            proxy=False,
            details="GPIO0 external active-low drive toggled GPIO IRQ aggregate",
        )
