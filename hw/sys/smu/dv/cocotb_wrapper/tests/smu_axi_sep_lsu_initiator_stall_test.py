# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_sep_lsu_initiator_stall_test - the SEP debug-module initiator on sep_out.

DV-TESTCASE-CONTRACT: TC_G4B ANCHOR: smu_axi_sep_lsu_initiator_stall_test
DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: d0773233ea122fa669324358a11984a38df6d41ec8ebedd389accff7dead3435
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_GAPS_VPLAN_DETAIL.md @ artifact_revision 5 ENV: cocotb

The SEP hart runs the ICCM probe under the debug module and the debug module's
system bus issues single accesses, both on sep_out, while the JTAG2AXI-programmed
SMC iDMA, JTAG2AXI and the ext_in master run against an ext_out responder that
withholds READY and delays B and R. Then interleaved IDs on every permitted
cell with one error response per link, the sep_out forwarding and SEP-aperture
DECERR cells, the ext_in DECERR bursts, the aperture edges from each initiator
with both apertures inside the SEP's SMU window, and the zero-size apertures.
Observation is passive. VCS is the run of record; the bench checkers print
their CHK-AXI-SVA lines at final, and on another simulator the leaf prints
INFO-RUN-MODE.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_sep_lsu_initiator_stall_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_concurrent_initiators_stall_test_seq import RESPONDER_DEPTH
from seq_lib.smu_axi_sep_lsu_initiator_stall_test_seq import (
    smu_axi_sep_lsu_initiator_stall_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_sep_lsu_initiator_stall_test(smu_base_test):
    """sep_out LSU probe and system bus with smc_out and ext_in partners; no Force."""

    use_shared_env = True

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg.axi_out_max_outstanding = RESPONDER_DEPTH

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_sep_lsu_initiator_stall_test AXI-SEP-LSU")
        seq = smu_axi_sep_lsu_initiator_stall_test_seq(self)
        await seq.run()
        assert seq.done, "SEP-initiator scenario did not reach its checkers"
