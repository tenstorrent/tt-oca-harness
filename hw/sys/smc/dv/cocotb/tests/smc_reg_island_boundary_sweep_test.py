# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boundary sweep of the 24 SMC register islands that declare a past-extent response.

Sources: smc.rdl (ocah_past_extent_resp), regs/gen/adoc/memory_map.adoc, regs/gen/py memory map.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_reg_island_boundary_sweep_test_seq import (
    smc_reg_island_boundary_sweep_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reg_island_boundary_sweep_test(smc_base_test):
    """Probe the first, last decoded, past-extent and aperture-end word of every island."""

    required_evidence = (
        "CHK-ISL-SETUP-GOLDENS",
        "CHK-ISL-FIRST-WORD-WRITE-OKAY",
        "CHK-ISL-LAST-DECODED-WORD-WRITE-OKAY",
        "CHK-ISL-PASTEXT-READ-DECERR",
        "CHK-ISL-PASTEXT-WRITE-DECERR-CLASS",
        "CHK-ISL-PASTEXT-WRITE-SLVERR-CLASS",
        "CHK-ISL-PASTEXT-NOCHANGE",
        "CHK-ISL-TABLE",
        "CHK-NONVAC",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reg_island_boundary_sweep_test_seq("smc_reg_island_boundary_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=seq.access_floor,
            csr_accesses=seq.accesses,
            proxy=False,
            details="24-island first, last decoded, past-extent and aperture-end probe sweep",
        )
