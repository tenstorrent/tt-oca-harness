# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang detector register field access, isolation and the SMC_ATTRIBUTES interrupt counts."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_irq_csr_readback_test_seq import smc_irq_csr_readback_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_irq_csr_readback_test(smc_base_test):
    """Frontdoor readback of the three hang detectors and the SMC_ATTRIBUTES counts."""

    required_evidence = (
        "CHK-ATTR-COUNTS-LOG",
        "CHK-HANGREG-CTRL-RW",
        "CHK-HANGREG-IRQ-RO",
        "CHK-HANGREG-ISOLATION",
        "CHK-HANGREG-THR-RANGE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_irq_csr_readback_test_seq("irq_csr_readback_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 7, f"phases {seq.phases}, want 7"
        assert seq.accesses >= 80, f"only {seq.accesses} SEP_IN accesses issued, want >= 80"
