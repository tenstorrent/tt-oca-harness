# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""NDMRESET_PROCESS bits at and above the cluster count are stored and not driven."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ndm_process_extra_bits_test_seq import smc_ndm_process_extra_bits_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ndm_process_extra_bits_test(smc_base_test):
    """Write 0xFFFFFFF0 to NDMRESET_PROCESS; process_o stays 0."""

    required_evidence = ("CHK-NDM-PROCESS-ABOVE-COUNT", "CHK-NONVAC")
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ndm_process_extra_bits_test_seq("ndm_process_extra_bits_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.process_readback == 0xFFFFFFF0 and seq.samples_taken == 64, (
            f"the sequence did not complete its compare "
            f"(readback={seq.process_readback}, samples={seq.samples_taken})"
        )
