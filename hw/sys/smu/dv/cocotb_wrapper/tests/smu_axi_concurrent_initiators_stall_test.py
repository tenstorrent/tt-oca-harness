# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_concurrent_initiators_stall_test - smc_out and ext_in against a stalling ext_out.

DV-TESTCASE-CONTRACT: TC_G4 ANCHOR: smu_axi_concurrent_initiators_stall_test
DV-TESTCASE-CONTRACT-REVISION: 4 RECORD-SHA256: fab38d0eb96479d56de4d70704fc2887b64408bd3830a3b785a69aa032349d76
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_GAPS_VPLAN_DETAIL.md @ artifact_revision 5 ENV: cocotb

The JTAG2AXI-programmed SMC iDMA copies between two ext_out ranges, JTAG2AXI
reads and writes ext_out, and the ext_in master sends requests to neither
aperture while the ext_out responder withholds READY and delays B and R. Then
interleaved IDs through both converters, the smc_out and ext_in forwarding
cells, the ext_in DECERR cell, the aperture edges at the reset sizes, the 57-bit
carry, the 32-bit SEP size edge and a reprogram with a read in flight. An SMC
request into the SMC aperture stays inside the SMC, so that DECERR cell is
printed as not drivable. The SEP aperture registers are written over the SEP
debug module's system bus; no SEP traffic is driven. Observation is passive.
VCS is the run of record; the bench checkers print their CHK-AXI-SVA lines at
final, and on another simulator the leaf prints INFO-RUN-MODE.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_concurrent_initiators_stall_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_concurrent_initiators_stall_test_seq import (
    RESPONDER_DEPTH,
    smu_axi_concurrent_initiators_stall_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_concurrent_initiators_stall_test(smu_base_test):
    """Concurrent smc_out and ext_in initiators, routing and aperture cells; no Force."""

    use_shared_env = True

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg.axi_out_max_outstanding = RESPONDER_DEPTH

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_concurrent_initiators_stall_test AXI-CONC")
        seq = smu_axi_concurrent_initiators_stall_test_seq(self)
        await seq.run()
        assert seq.done, "concurrent-initiator scenario did not reach its checkers"
