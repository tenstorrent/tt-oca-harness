# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sources from every region of the raw interrupt vector assert together and drop one by one."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_irq_vector_assembly_test_seq import smc_irq_vector_assembly_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_irq_vector_assembly_test(smc_base_test):
    """Ext, SEP mailbox, NDM, hang, inbound mailbox and zeroer sources against the baseline."""

    required_evidence = (
        "CHK-VECASM-ALL-REGIONS",
        "CHK-VECASM-DROP-EACH",
        "CHK-VECASM-HOLD",
        "CHK-VECASM-RSVD-287",
        "CHK-VECASM-TAIL-ZERO",
        "CHK-VECASM-EDGES",
        "CHK-VECASM-INBOUND-LOG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_irq_vector_assembly_test_seq("irq_vector_assembly_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 27, f"only {seq.accesses} SEP_IN accesses issued, want >= 27"
