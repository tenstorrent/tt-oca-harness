# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_sep_reset_in_flight_test - the SEP-facing links across one IC_RESET hold.

DV-TESTCASE-CONTRACT: TC_G2B ANCHOR: smu_axi_sep_reset_in_flight_test
DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 095844da013017357b99a6012cecc23f650d18c4b91a91f85c8fc0ab9703e369
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_GAPS_VPLAN_DETAIL.md @ artifact_revision 5 ENV: cocotb

The DTP IC_RESET TDR override holds sep_reset_n low once, with the SMC primary
reset high, while ext_in reads and writes and a JTAG2AXI operation toward the
SEP SRAM and a SEP CPU egress store toward a stalled ext_out are outstanding.
The SEP-originated traffic is the ICCM stub of smu_sep_reset_inflight_test
under the debug module, plus the debug module's system bus. The leaf samples
the SEP-driven VALIDs on every clk_smu_i edge of the hold, holds every
response against its issue log, grades the bench expectation window, and
after the release alone runs a fresh write and read on every route, the
SEP-to-SMC accesses included; the one cold reset comes last. Observation is
passive. VCS is the run of record; the bench checkers print their CHK-AXI-SVA
lines at final.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_sep_reset_in_flight_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_sep_reset_in_flight_test_seq import (
    EVIDENCE,
    smu_axi_sep_reset_in_flight_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_sep_reset_in_flight_test(smu_base_test):
    """One SEP debug hold with SEP-originated, ext_in and JTAG2AXI traffic in flight; no Force."""

    use_shared_env = True
    required_evidence = EVIDENCE
    # AXI monitor ext_in READY rule: ext_in ARs wait on the DUT across the SEP reset hold.
    axi_monitor_ready_budget_ext_in = False

    async def run_scenario(self) -> None:
        self.logger.info(
            "INFO-DUT_TAG=WRAPPER smu_axi_sep_reset_in_flight_test SEP=1 IC_RESET SEP hold"
        )
        seq = smu_axi_sep_reset_in_flight_test_seq(self)
        await seq.run()
        assert seq.done, f"SEP reset in-flight scenario incomplete steps={seq.steps}"
