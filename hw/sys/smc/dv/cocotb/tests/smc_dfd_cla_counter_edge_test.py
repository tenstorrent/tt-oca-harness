# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Make the CLA counters count and walk the edge-detect configuration surface.

Arms the CLA with the debug bus in normal debug mode, walks every value of the
two edge-detect select fields and both polarities, then drives `Action0` over
its whole range and reads the hardware-driven counter fields of all four CLA
counters back after each value.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_cla_counter_edge_test_seq import smc_dfd_cla_counter_edge_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Bounded polls can add reads,
# never remove them, so this is the count with every poll satisfied first time.
#
#   DEBUG_CTRL force_clk_en write                                             1
#   64 values of the 6-bit Dbmid field, normal debug mode                    64
#   4 counter reset reads                                                     4
#   4 counter target writes                                                   4
#   CLA arm: EAP reset write, CDbgClaCtrlStatus write, then per LogicalOp
#     value a configuration write and a CDbgEapStatus read until one
#     activates                                                               4
#   128 edge-detect select values, each a write and a readback              256
#   64 Action0 values, each a write and one read of each of the 4 counters  320
#   restore: 4 counters, edge-detect, EAP, CLA control, DEBUG_BUS_MUX,
#     DEBUG_CTRL                                                              9
#                                                                         ------
#                                                                            662
CLA_COUNTER_EDGE_MIN_CSR_ACCESSES = 662


@pyuvm.test()
class smc_dfd_cla_counter_edge_test(smc_base_test):
    """Drive the CLA counters from the action bus and walk the edge-detect selects."""

    required_evidence = (
        "CHK-CLA-COUNTER-CLEARS",
        "CHK-CLA-COUNTER-COUNTS",
        "CHK-CLA-COUNTER-RESET",
        "CHK-CLA-EDGE-SELECT-SWEEP",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_counter_edge_test_seq("cla_counter_edge_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLA_COUNTER_EDGE_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"counters seen counting {sorted(seq.counted)}, cleared "
                f"{sorted(seq.cleared)}, {seq.selects_walked} edge-detect select values"
            ),
        )
