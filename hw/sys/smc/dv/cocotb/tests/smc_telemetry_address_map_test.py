# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC telemetry receiver wrapper address map: offsets, counters, past-extent, unbacked."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_address_map_test_seq import smc_telemetry_address_map_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_address_map_test(smc_base_test):
    """Receivers 0 to 2 register and counter offsets; past-extent and unbacked responses."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TELEMETRY-APERTURE-REGS",
        "CHK-TELEMETRY-COUNTER-WINDOW",
        "CHK-TELEMETRY-NO-FOURTH-RECEIVER",
        "CHK-TELEMETRY-PAST-EXTENT",
        "CHK-TELEMETRY-UNBACKED-OFFSETS",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_address_map_test_seq("smc_telemetry_address_map_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            # 21 register reads, 6 pattern writes and reads, 3 counter-window
            # rounds of 6 reads, 32 counter reads, past-extent and unbacked probes.
            min_csr_accesses=80,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Telemetry receiver wrapper address map across three apertures",
        )
