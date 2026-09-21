# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: GPIO_CTRL 46-entry full sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_ctrl_full_sweep_test_seq import smc_gpio_ctrl_full_sweep_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_ctrl_full_sweep_test(smc_base_test):
    """P1 coverage-gap depth: GPIO_CTRL 46-entry full sweep."""

    required_evidence = ("CHK-GPIO-CTRL-WINDOW-ERROR-SWEEP",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_ctrl_full_sweep_test_seq("smc_gpio_ctrl_full_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            # Directed stimulus floor: 65 GPIO_CTRL window reads (one per
            # bootrom EXTERNAL_MANDATORY GPIO_CTRL instance). Literal here, not
            # read from `seq.accesses`.
            min_csr_accesses=65,
            csr_accesses=seq.accesses,
            proxy=True,
            details=("U5 GPIO_CTRL RW-stub WR->RD sweep (CSR storage, not pad protocol)"),
        )
