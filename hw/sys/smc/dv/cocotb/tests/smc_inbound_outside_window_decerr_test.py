# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outside-window DECERR of the input-fabric region demux on sys_axi_in and sep_axi_in.

Spec sources: memmap.adoc Memory Map, fabric.adoc Fabric Topology, smc_base_config.rdl REGION_SIZE.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_inbound_outside_window_decerr_test_seq import (
    smc_inbound_outside_window_decerr_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: 8 filter setup/restore, 6 S2 reads, 8 + 8 + 8 + 16 + 32 DECERR-class
# accesses and one live control read.
STIMULUS_FLOOR = 87


@pyuvm.test()
class smc_inbound_outside_window_decerr_test(smc_base_test):
    """DECERR outside both windows and at BASE+REGION_SIZE on both inbound ports."""

    required_evidence = (
        "CHK-REGION-SIZE-LIMIT-DECERR",
        "CHK-BELOW-BASE-DECERR",
        "CHK-WINDOW-LAST-WORD-ROUTED",
        "CHK-OUTSIDE-WINDOW-DECERR",
        "CHK-OUTSIDE-NO-OUTPUT-REQUEST",
        "CHK-REMAP-REGION-RESET-DECERR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_inbound_outside_window_decerr_test_seq("inbound_outside_window_decerr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "INBOUND_OUTSIDE_WINDOW_DECERR")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
