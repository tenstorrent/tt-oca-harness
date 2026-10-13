# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Manager-side channel skew and ready timing on the three inbound ports.

Contract SMC_AXI_CHANNEL_TIMING_PORTS_TEST, anchor smc_axi_channel_timing_ports_test.
Allocated scenarios: AXI-W-BEFORE-AW.S1/S2/S3, AXI-AW-BEFORE-W.S1/S2/S3, AXI-BREADY-HOLD.S3,
AXI-RREADY-HOLD.S2, AXI-BACKPRESSURE.S1.
Spec sources: fabric.adoc Topology and Configuration Parameters, scratch.rdl SCRATCH sw=rw.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axi_channel_timing_ports_test_seq import (
    smc_axi_channel_timing_ports_test_seq,
)
from smc_base_test import smc_base_test

# Accesses issued across the three ports: 3 setup writes, 103 + 77 + 77 timed-port accesses
# and 11 teardown writes on SEP_IN.
STIMULUS_FLOOR = 257


@pyuvm.test()
class smc_axi_channel_timing_ports_test(smc_base_test):
    """Skew, hold and stall AW, W, AR, B and R on SEP_IN, SYS_IN and JTAG."""

    required_evidence = (
        "CHK-CTP-W-FIRST",
        "CHK-CTP-AW-FIRST",
        "CHK-CTP-AW-QUEUE",
        "CHK-CTP-BREADY-PORTS",
        "CHK-CTP-RREADY-BEATS",
        "CHK-CTP-RANDOM-STALLS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_axi_channel_timing_ports_test_seq("axi_channel_timing_ports_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "AXI_CHANNEL_TIMING_PORTS")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
