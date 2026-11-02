# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: TC_M4 ANCHOR: smc_axi_fabric_burst_type_islands_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 97dba3f67449f660c3fb954a12d88e28546a257a7f91f0e4364edd1f968d702a
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_AXI_FAB_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""FIXED, WRAP and INCR bursts from SEP_IN, SYS_IN and JTAG_IN at the SMC register islands.

Drives the three burst types at the 64-bit islands behind the AXI-to-AXI-Lite conversion
(alias remap slot 2, the base-config hang-detector window, CPU-control SCRATCH), the 32-bit
islands behind the 64-to-32-bit downsizer (misc scratch words, reset-unit FLR counters),
partial-strobe writes to 32-bit pairs, a GPIO slot bank, the scratchpad RAM and ROM, an
alias-remap slot edge, the island extent edges, the scratchpad and CPU-control rule ends and
the inbound window end at the reset REGION_SIZE and at REGION_SIZE=0x400, recovered by a
primary reset through the cool pin. Protocol, out-of-footprint registers, strobed lanes and a
LOCAL_BASE liveness read are graded from a passive per-port handshake sampler; responses and
landings the specification leaves open are OBS lines.

Run (VCS: the ocah_axi_sva rules grade on VCS only):
    python3 tools/dv/run_dv.py --dut smc --items smc_axi_fabric_burst_type_islands_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_axi_fabric_burst_type_islands_test_seq import (
    smc_axi_fabric_burst_type_islands_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axi_fabric_burst_type_islands_test(smc_base_test):
    """Grade FIXED, WRAP and INCR bursts at the register islands and edges on all inbound ports."""

    required_evidence = (
        "CHK-BT-EXTENTEDGE",
        "CHK-BT-GPIO",
        "CHK-BT-ISLAND32",
        "CHK-BT-ISLAND64",
        "CHK-BT-REGIONEDGE",
        "CHK-BT-RULEEDGE",
        "CHK-BT-SLOTEDGE",
        "CHK-BT-SPM",
        "CHK-BT-STRB-UPPER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    async def run_scenario(self) -> None:
        seq = smc_axi_fabric_burst_type_islands_test_seq("burst_type_islands_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.log_timeout_paths()
        seq.nonvac_fence()
        seq.raise_findings()
