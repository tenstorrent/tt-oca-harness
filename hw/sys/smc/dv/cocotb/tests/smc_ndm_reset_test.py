# SPDX-License-Identifier: Apache-2.0
"""NDM request pin to REQUEST/IRQ to PROCESS CSR to process_o."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_ndm_reset_test_seq import smc_ndm_reset_test_seq


@pyuvm.test()
class smc_ndm_reset_test(smc_base_test):
    """Per-cluster NDM handshake without Force or firmware."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ndm_reset_test_seq("ndm_reset_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.count_ok and seq.bits_ok, (
            f"ndm handshake incomplete count={seq.count_ok} bits={seq.bits_ok}"
        )
