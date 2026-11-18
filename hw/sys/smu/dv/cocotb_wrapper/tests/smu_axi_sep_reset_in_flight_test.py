# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_sep_reset_in_flight_test - the SEP-facing links across one IC_RESET hold.

DV-TESTCASE-CONTRACT: TC_G2B ANCHOR: smu_axi_sep_reset_in_flight_test
DV-TESTCASE-CONTRACT-REVISION: 5 RECORD-SHA256: 996912a4bc3cf9026ab6be8e3b76f3cebe20273d91c4786da51c176212a6e62d
DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smu/dv/ai/dv_vplan_gen/SMU_AXI_GAPS_VPLAN_DETAIL.md @ artifact_revision 9 ENV: cocotb

The DTP IC_RESET TDR override holds sep_reset_n low once, with the SMC primary
reset high, while ext_in reads and writes toward the SEP SRAM, with BREADY and
RREADY withheld, and a SEP CPU egress store toward a stalled ext_out are
outstanding. The JTAG2AXI write and read toward the SEP SRAM issued before the
hold complete before the fall: the bridge holds one operation and drives its
own BREADY and RREADY, so the leaf prints INFO-CELL-NOT-DRIVABLE for that cell.
The JTAG2AXI read issued during the hold is accepted on sep_in and gets no
response; no checker expects one, and that read and the JTAG2AXI read after the
release are observations of an open spec question (whether a request accepted
before a reset completes or is withdrawn). The response check on dtp_dbg covers
both reads and the bridge writes after the release.
The SEP-originated traffic is the ICCM stub of smu_sep_reset_inflight_test
under the debug module, plus the debug module's system bus. Nothing
SEP-driven is pending at the fall, so the SEP-driven VALIDs the leaf samples
on every clk_smu_i edge of the hold, with the count pending at the fall, are
observations. The leaf holds every response against its issue log, grades the
bench expectation window, and after the release and a TAP test-logic reset,
with no cold reset, runs a fresh write and read on every route, the
SEP-to-SMC accesses included, with each bridge write read back over ext_in or
the debug module's system bus; the one cold reset comes last. It prints one
line per required cell of its scenarios. Observation is passive. VCS is the run of record; the bench checkers print their CHK-AXI-SVA
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
