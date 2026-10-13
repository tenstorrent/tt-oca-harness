# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Generated cpuif contract edges over SEP_IN: partial strobe, write-only, unreadable, past extent.

Contract SMC_CPUIF_RO_WO_EDGE_TEST, anchor smc_cpuif_ro_wo_edge_test.
Allocated scenarios: REGBLOCK-RO-WRITE.S2, REGBLOCK-WO-READ.S2, REGBLOCK-UNREADABLE-READ.S1/S2/S3.
Spec sources: smc.rdl chip_config VERSION_LO sw=r, scratch.rdl SCRATCH[7] sw=rw, SF-001/008/009/010.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpuif_ro_wo_edge_test_seq import smc_cpuif_ro_wo_edge_test_seq
from smc_base_test import smc_base_test

# Baseline and setup 2, three strobed writes with a readback each 6, then S3 3, S4 2, S5 2,
# S6 3.
STIMULUS_FLOOR = 18


@pyuvm.test()
class smc_cpuif_ro_wo_edge_test(smc_base_test):
    """Partial-strobe write at a read-only register and the unreadable and past-extent edges."""

    required_evidence = (
        "CHK-EDGE-RO-PARTIAL",
        "CHK-EDGE-WO-WRITE-READ-OBS",
        "CHK-EDGE-UNREADABLE-OBS",
        "CHK-EDGE-PAST-EXTENT-OBS",
        "CHK-EDGE-RECOVERY",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpuif_ro_wo_edge_test_seq("smc_cpuif_ro_wo_edge_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "CPUIF_RO_WO_EDGE")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
