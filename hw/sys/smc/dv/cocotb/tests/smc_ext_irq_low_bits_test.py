# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""External input bits 1 and 0 on their dedicated pins against raw tb_cpu_interrupts bits."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_irq_low_bits_test_seq import smc_ext_irq_low_bits_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_irq_low_bits_test(smc_base_test):
    """Each pin alone and both in either release order, whole-vector compare to the baseline."""

    required_evidence = (
        "CHK-LOW2-BIT0",
        "CHK-LOW2-BIT1",
        "CHK-LOW2-BOTH-BIT0-FIRST",
        "CHK-LOW2-BOTH-BIT1-FIRST",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_irq_low_bits_test_seq("ext_irq_low_bits_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 10, f"phases {seq.phases}, want 10"
        assert seq.accesses >= 1, f"only {seq.accesses} SEP_IN accesses issued, want >= 1"
