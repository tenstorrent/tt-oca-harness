# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 raw ATB beat capture, TELEMETRY_DATA readout and both flush paths."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_atb_capture_test_seq import smc_telemetry_atb_capture_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_atb_capture_test(smc_base_test):
    """Capture raw ATB beats on receiver 0, drain them through TELEMETRY_DATA, and flush."""

    required_evidence = (
        "CHK-TELEMETRY-RAW-CAPTURE-IN-ORDER",
        "CHK-TELEMETRY-EMPTY-READ-NO-POP",
        "CHK-TELEMETRY-FULL-BACKPRESSURE",
        "CHK-TELEMETRY-BACK-TO-BACK-POP",
        "CHK-TELEMETRY-RX-FLUSH-WHILE-FULL",
        "CHK-TELEMETRY-THRESHOLD-BEATS",
        "CHK-TELEMETRY-TX-FLUSH-WHILE-DRAINING",
        "CHK-TELEMETRY-WRITE-NO-POP",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_atb_capture_test_seq("smc_telemetry_atb_capture_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            # Directed stimulus floor: one TELEMETRY_DATA read for each of
            # the 41 beats of the full-FIFO drain alone.
            min_csr_accesses=41,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Telemetry raw ATB beat capture plus receiver and transmitter flush",
        )
