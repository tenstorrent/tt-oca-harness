# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer job breadth: aligned beats, restart, 56-bit destination and a random job mix.

Sources hw/sys/smc/doc/zeroer.adoc, hw/ip/zeroer/regs/zeroer_ctrl.rdl.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_job_breadth_test_seq import smc_zeroer_job_breadth_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, independent of the sequence's own counter:
#   6 output-fabric pass-all filter writes                               6
#   24 jobs, each at least one start write and one STATUS poll          48
ZEROER_JOB_BREADTH_MIN_CSR_ACCESSES = 54


@pyuvm.test()
class smc_zeroer_job_breadth_test(smc_base_test):
    """Aligned job beats, restart, high destination address and a random job mix."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-ZEROER-JOB-ALIGNED-BEATS",
        "CHK-ZEROER-JOB-HIGH-ADDR",
        "CHK-ZEROER-JOB-RANDOM",
        "CHK-ZEROER-JOB-RESTART",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_job_breadth_test_seq("smc_zeroer_job_breadth_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_JOB_BREADTH_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"{seq.runs} zeroer job(s) completed",
        )
