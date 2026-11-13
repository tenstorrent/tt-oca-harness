# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_smc_cool_reset_in_flight_test - SMU AXI links across the SMC primary reset.

DV-TESTCASE-CONTRACT: TC_G2A ANCHOR: smu_axi_smc_cool_reset_in_flight_test
DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: e4ba3aafecd05806fc545f434fa6f406c96c3d9cef9d086b9f2866ec06cc1882
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_GAPS_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb

ext_in reads and writes are left accepted and unanswered, and one JTAG2AXI
access toward ext_out is issued, while the cool-reset pin, and then an FLR
request, assert the SMC primary reset; no response is held by the bench
responder in those legs. Every checked link is sampled: VALIDs low in reset,
handshakes resolved from release, no response after release for a request
issued before it, and a fresh write and read on every route that answered OKAY
before the reset. The last leg holds one B on the responder across a cool
reset; the responder drops it at the primary reset, the link's aresetn, and
OBS-G2A-HELD-RESP records what the DUT presents after release. VCS only; the
bench checkers print their CHK-AXI-SVA and CHK-AXI-STALL lines at final.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_smc_cool_reset_in_flight_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_smc_cool_reset_in_flight_test_seq import (
    RESPONDER_DEPTH,
    smu_axi_smc_cool_reset_in_flight_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_smc_cool_reset_in_flight_test(smu_base_test):
    """Requests in flight across the cool and FLR primary resets; no Force."""

    use_shared_env = True

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg.axi_out_max_outstanding = RESPONDER_DEPTH

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_smc_cool_reset_in_flight_test AXI-RESET")
        seq = smu_axi_smc_cool_reset_in_flight_test_seq(self)
        await seq.run()
        assert seq.done, "cool-reset in-flight scenario did not reach its checkers"
