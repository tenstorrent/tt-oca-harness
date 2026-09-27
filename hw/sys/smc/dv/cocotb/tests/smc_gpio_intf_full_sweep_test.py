# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO_INTF full 65-entry sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_intf_full_sweep_test_seq import smc_gpio_intf_full_sweep_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_intf_full_sweep_test(smc_base_test):
    """GPIO_INTF full 65-entry sweep."""

    required_evidence = ("CHK-GPIO-INTF-DATA-CTRL-SWEEP",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_intf_full_sweep_test_seq("smc_gpio_intf_full_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            # Directed stimulus floor: 65 GPIO_INTF DATA_CTRL accesses (one per
            # pad entry). Literal here, not read from `seq.accesses`.
            min_csr_accesses=65,
            csr_accesses=seq.accesses,
            proxy=False,
            details="GPIO_INTF full 65-entry sweep",
        )
