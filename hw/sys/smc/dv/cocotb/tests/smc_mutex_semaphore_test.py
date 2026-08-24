# SPDX-License-Identifier: Apache-2.0
"""CPU_CTRL MUTEX[0] take and release."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_mutex_semaphore_test_seq import smc_mutex_semaphore_test_seq


@pyuvm.test()
class smc_mutex_semaphore_test(smc_base_test):
    """CPU_CTRL MUTEX[0] available / taken / released over SEP_IN AXI."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mutex_semaphore_test_seq("mutex_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.take_ok and seq.held_ok and seq.release_ok, (
            f"mutex incomplete take={seq.take_ok} held={seq.held_ok} "
            f"rel={seq.release_ok}"
        )
