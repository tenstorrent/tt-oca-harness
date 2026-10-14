# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver flush on receiver 0.

Sources: hw/ip/telemetry_receiver/doc/architecture.adoc, hw/ip/telemetry_receiver/regs/
telemetry_receiver.rdl, doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_rx_flush_test_seq import smc_telemetry_rx_flush_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_rx_flush_test(smc_base_test):
    """Receiver flush of the queue, the assembly pointer and the interrupt state."""

    required_evidence = (
        "CHK-TELEMETRY-RX-FLUSH-EMPTIES",
        "CHK-TELEMETRY-RX-FLUSH-ONE-SHOT",
        "CHK-TELEMETRY-RX-FLUSH-RESTART",
        "CHK-TELEMETRY-RX-FLUSH-MID-MESSAGE",
        "CHK-TELEMETRY-RX-FLUSH-BEATS-AROUND",
        "CHK-TELEMETRY-RX-FLUSH-KEEPS-MISSING-LAST",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_rx_flush_test_seq("smc_telemetry_rx_flush_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=40,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Telemetry receiver 0 flush of queue, assembly pointer and interrupt state",
        )
