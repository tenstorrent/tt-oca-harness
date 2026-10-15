# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 register access.

Sources: hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl,
doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_ctrl_access_test_seq import smc_telemetry_ctrl_access_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_ctrl_access_test(smc_base_test):
    """CTRL, INTR_ENABLE and INTR_TEST field access and read-only register writes."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TELEMETRY-CTRL-FULL-WORD",
        "CHK-TELEMETRY-CTRL-PULSE-READ",
        "CHK-TELEMETRY-INTR-ENABLE-BITS",
        "CHK-TELEMETRY-INTR-TEST-ACCESS",
        "CHK-TELEMETRY-RO-WRITE-IGNORED",
        "CHK-TELEMETRY-THRESHOLD-FIELD-RW",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_ctrl_access_test_seq("smc_telemetry_ctrl_access_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=60,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Telemetry receiver 0 CTRL, INTR_ENABLE, INTR_TEST and read-only registers",
        )
