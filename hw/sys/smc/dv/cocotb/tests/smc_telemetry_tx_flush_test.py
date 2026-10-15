# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry transmitter flush on receiver 0.

Sources: hw/ip/telemetry_receiver/doc/architecture.adoc, doc/interface.adoc,
hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl, doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_tx_flush_test_seq import smc_telemetry_tx_flush_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_tx_flush_test(smc_base_test):
    """Transmitter flush over the ATB AF handshake on receiver 0."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TELEMETRY-FLUSH-PATH-SEPARATION",
        "CHK-TELEMETRY-TX-FLUSH-PENDING-HOLD",
        "CHK-TELEMETRY-TX-FLUSH-READY-HIGH",
        "CHK-TELEMETRY-TX-FLUSH-REWRITE",
        "CHK-TELEMETRY-TX-FLUSH-THRESHOLD-KEPT",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_tx_flush_test_seq("smc_telemetry_tx_flush_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=40,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Telemetry receiver 0 transmitter flush handshake, hold and rewrite",
        )
