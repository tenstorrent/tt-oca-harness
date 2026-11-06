# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each I3C instance's interrupt reaches its own peripheral-interrupt bit, 12 to 17.

On every instance the PIO response-ready interrupt is forced through
`PIO_INTR_FORCE` and the bench's `tb_i3c_irq` slice of `peripheral_interrupts`
must read exactly that instance's bit, then nothing once the force is cleared.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i3c_irq_route_test_seq import NUM_I3C, smc_i3c_irq_route_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_irq_route_test(smc_base_test):
    """Force each I3C instance's interrupt and watch the six PLIC lines."""

    required_evidence = ("CHK-I3C-IRQ-ROUTE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_irq_route_test_seq("smc_i3c_irq_route_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.routed == list(range(NUM_I3C)), (
            f"instances routed {seq.routed}, expected all {NUM_I3C}"
        )
