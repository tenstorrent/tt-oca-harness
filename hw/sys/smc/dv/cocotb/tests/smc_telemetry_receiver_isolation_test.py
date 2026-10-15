# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receivers 0, 1 and 2: traffic and CSR operations stay on one receiver."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_receiver_isolation_test_seq import (
    smc_telemetry_receiver_isolation_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_receiver_isolation_test(smc_base_test):
    """Single-receiver traffic, simultaneous traffic and CSR operations against the others."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TELEMETRY-ISOLATION-OPS",
        "CHK-TELEMETRY-ISOLATION-SIMULTANEOUS",
        "CHK-TELEMETRY-ISOLATION-TRAFFIC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_receiver_isolation_test_seq("smc_telemetry_receiver_isolation_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            # Floor: the S1 flush, enable and clock-gate accesses, the S2 snapshots of two
            # receivers three times, the S3 and S4 reads and writes.
            min_csr_accesses=120,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Telemetry receiver isolation across traffic and CSR operations",
        )
