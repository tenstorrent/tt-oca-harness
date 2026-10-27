# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ISOLATE_REQ_SMC_REG clears only on a write of 1 to bit 0 on its own byte lane.

A one-byte write of 0 at byte 1, a one-byte write of 0xFF at byte 1 and a word
write of 0 must each leave the FLR-latched request reading 1; a write of 1 to
bit 0 must clear it, per the RDL's `onwrite = woclr` field at bit 0.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_isolate_req_smc_lane_test_seq import smc_isolate_req_smc_lane_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_isolate_req_smc_lane_test(smc_base_test):
    """Raise the request through FLR, write lane 1 and a word of 0, then clear with a 1 at bit 0."""

    required_evidence = ("CHK-ISOLATE-REQ-SMC-LANE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_isolate_req_smc_lane_test_seq("smc_isolate_req_smc_lane_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
