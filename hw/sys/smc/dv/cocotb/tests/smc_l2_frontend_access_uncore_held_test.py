# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: TC_M1 ANCHOR: smc_l2_frontend_access_uncore_held_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 5bd55eaaa1f25a1205cd40fc9161287c36075fe299943ad3d1bab0535b388b8d
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_AXI_FAB_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""L2-frontend requests from SYS_IN, SEP_IN and JTAG_IN while a software uncore reset holds the cluster.

A drained RESET_CTRL uncore reset from SEP_IN, CPU_CTRL accesses while running and held,
scratchpad and boot-ROM reads and scratchpad writes presented during the hold (no response
for a counted window, completion after the release), the cluster-side VALIDs of both
isolation blocks on every edge of the hold, and fresh INCR bursts afterwards. Graded from a
passive per-port handshake sampler; open values (SF-016, SF-017, SF-018, SF-019, SF-026) are
OBS lines.

Run (VCS: the ocah_axi_sva rules grade on VCS only):
    python3 tools/dv/run_dv.py --dut smc --items smc_l2_frontend_access_uncore_held_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_l2_frontend_access_uncore_held_test_seq import (
    smc_l2_frontend_access_uncore_held_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_l2_frontend_access_uncore_held_test(smc_base_test):
    """Grade the L2-frontend boundary and the CPU-control path across a drained uncore reset."""

    required_evidence = (
        "CHK-FRONTPORT-CTRL",
        "CHK-ISO-BLOCK-NO-RESPONSE",
        "CHK-ISO-DRAIN-APPLIED",
        "CHK-ISO-RECONNECT",
        "CHK-ISO-VALIDS-CLUSTER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    async def run_scenario(self) -> None:
        seq = smc_l2_frontend_access_uncore_held_test_seq("l2_frontend_access_uncore_held_seq")
        try:
            await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        except BaseException:
            seq.log_timeout_paths()
            seq.nonvac_fence()
            raise
        seq.log_timeout_paths()
        seq.nonvac_fence()
        seq.raise_findings()
