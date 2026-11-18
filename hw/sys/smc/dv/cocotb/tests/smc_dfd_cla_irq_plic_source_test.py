# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CLA debug interrupt is PLIC source 322, and the clock-stop source 321 stays idle.

The debug-interrupt action, found by walking `Action0`, raises
`tb_cla_interrupt`; `tb_plic_pending_322` is 0 on every sample before that
and 1 within four polls after it, and `tb_plic_pending_321` is 0 throughout.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfd_cla_irq_plic_source_test_seq import smc_dfd_cla_irq_plic_source_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_cla_irq_plic_source_test(smc_base_test):
    """Fire the debug-interrupt action and grade the PLIC pending bits 321 and 322."""

    required_evidence = ("CHK-CLA-IRQ-PLIC-322",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_irq_plic_source_test_seq("smc_dfd_cla_irq_plic_source_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
