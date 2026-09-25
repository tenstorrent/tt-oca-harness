# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 ATB message capture and both flush paths."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_atb_capture_test_seq import smc_telemetry_atb_capture_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_atb_capture_test(smc_base_test):
    """Capture one ATB message on receiver 0 and drive the receiver and transmitter flushes."""

    required_evidence = (
        "CHK-TELEMETRY-ATB-MESSAGE-CAPTURE",
        "CHK-TELEMETRY-RX-FLUSH",
        "CHK-TELEMETRY-TX-FLUSH-HANDSHAKE",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_atb_capture_test_seq("smc_telemetry_atb_capture_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            # Directed stimulus floor: 4 CLOCK_GATE_CONTROL accesses, the entry
            # STATUS read, 4 message-readback reads, the BUFFER_POP write, the
            # two flush-request writes with their readbacks, the two
            # TX_FLUSH CTRL reads, and one STATUS poll per buffer wait.
            min_csr_accesses=20,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Telemetry ATB message capture plus receiver and transmitter flush",
        )
