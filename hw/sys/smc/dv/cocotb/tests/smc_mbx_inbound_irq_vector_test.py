# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound mailbox interrupts at raw tb_cpu_interrupts bits 319:288 and PLIC sources 289 to 320."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mbx_inbound_irq_vector_test_seq import smc_mbx_inbound_irq_vector_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mbx_inbound_irq_vector_test(smc_base_test):
    """Single, grouped and clear-one pushes: raw bit 288 + m and PLIC source 289 + m per mailbox."""

    required_evidence = (
        "CHK-MBXIN-CLEAR",
        "CHK-MBXIN-MULTI",
        "CHK-MBXIN-POSITION",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mbx_inbound_irq_vector_test_seq("mbx_inbound_irq_vector_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 200, f"only {seq.accesses} SEP_IN accesses issued, want >= 200"
