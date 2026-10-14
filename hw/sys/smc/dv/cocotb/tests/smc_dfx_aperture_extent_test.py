# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""dfx_ctrl register addresses, past-extent DECERR and the gap at offset 0xC.

Spec: smc.rdl dfx_ctrl placement, dfx_ctrl_status.rdl address map, memmap.adoc address space.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfx_aperture_extent_test_seq import smc_dfx_aperture_extent_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfx_aperture_extent_test(smc_base_test):
    """dfx_ctrl aperture: registers, past-extent DECERR, next block, gap."""

    required_evidence = (
        "CHK-APERTURE-HOLE",
        "CHK-APERTURE-NEXT-BLOCK",
        "CHK-APERTURE-PAST-READ",
        "CHK-APERTURE-PAST-WRITE",
        "CHK-APERTURE-REGISTERS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfx_aperture_extent_test_seq("dfx_aperture_extent_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
