# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang-detector IRQ reaches the PLIC source pin. No CPU firmware."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_hang_detector_plic_route_test_seq import (
    smc_hang_detector_plic_route_test_seq,
)


@pyuvm.test()
class smc_hang_detector_plic_route_test(smc_base_test):
    """peripheral_interrupts[31] carries the hang OR into cpu_interrupts."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_plic_route_test_seq("hang_detector_plic_route_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert (
            seq.idle_ok and seq.gated_ok and seq.route_ok and seq.shared_slot_ok
        ), (
            f"hang detector PLIC route incomplete idle={seq.idle_ok} "
            f"gated={seq.gated_ok} route={seq.route_ok} shared={seq.shared_slot_ok}"
        )
