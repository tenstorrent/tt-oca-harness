# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang-detector IRQ reaches the PLIC source pin. No CPU firmware."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_detector_plic_route_test_seq import (
    smc_hang_detector_plic_route_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_detector_plic_route_test(smc_base_test):
    """peripheral_interrupts[30] carries the hang OR into cpu_interrupts."""

    required_evidence = (
        "CHK-HANG-PLIC-DATA-CLR",
        "CHK-HANG-PLIC-DATA-FIRE",
        "CHK-HANG-PLIC-GATED",
        "CHK-HANG-PLIC-IDLE",
        "CHK-HANG-PLIC-ROUTE",
        "CHK-HANG-PLIC-SEP-CLR",
        "CHK-HANG-PLIC-SEP-FIRE",
        "CHK-HANG-PLIC-SHARED-CLR",
        "CHK-HANG-PLIC-SHARED-HOLD",
        "CHK-HANG-PLIC-SYS-CLR",
        "CHK-HANG-PLIC-SYS-FIRE",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_plic_route_test_seq("hang_detector_plic_route_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.gated_ok and seq.route_ok and seq.shared_slot_ok, (
            f"hang detector PLIC route incomplete idle={seq.idle_ok} "
            f"gated={seq.gated_ok} route={seq.route_ok} shared={seq.shared_slot_ok}"
        )
