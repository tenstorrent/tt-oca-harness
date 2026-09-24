# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive the CLA's signal event generators, counters and action outputs on a moving bus.

Gives the CLA a debug bus that moves between two measured states, programs the
edge, change, transition, comparator and LFSR generators from them, drives the
action field with the cross-trigger stretch, clock halt and counter reset on
target enabled, and moves the node chain away from pairs whose relation holds.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_cla_live_bus_test_seq import smc_dfd_cla_live_bus_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every discovery loop and poll
# is counted at one iteration, the shortest each can finish in.
#
#   DEBUG_CTRL force write, the CLA arm, one relation try (write, status read)  4
#   64 CLA mux writes                                                        64
#   sampled-mux discovery: 64 identifier-mode writes, the two-word
#     snapshot, one probe (write and two-word snapshot)                      69
#   generators: edge, change, transition mask/from/to, 4 x (comparator value
#     and mask), each write + readback, and the LFSR write + readback        28
#   2 passes of 16 bus switches x (mux write and two-word snapshot), and the
#     swapped edge configuration write + readback between them               98
#   match events: 4 mask/match writes + readbacks, then 2 event pairs x 4
#     relation values x (pair write, 2 status writes, 4 mux writes, the
#     status read), and the pair quiesce                                      73
#   running-counter search: the counter set-up write + readback, one try
#     (action write, enable off, 2 counter reads, enable on), then 64 x
#     (running-action write, action write, counter target write)            199
#   actions: stretch write + readback, 4 counter writes + readbacks, 3 CLA
#     control writes, 3 sweeps of 64 action writes, 4 counter reads         209
#   2 custom-action enables and Resync, each write + readback                 6
#   leaving the node: one relation try (write, status read), 3 destination
#     writes, the move write and one CurrentNode read                         7
#   restore: 4 pairs, 4 counters, 14 named registers, 8 comparator
#     registers, DEBUG_BUS_MUX, DEBUG_CTRL                                   32
#                                                                         ------
#                                                                           789
CLA_LIVE_BUS_MIN_CSR_ACCESSES = 789


@pyuvm.test()
class smc_dfd_cla_live_bus_test(smc_base_test):
    """Program the CLA generators from a moving bus and drive its actions."""

    required_evidence = (
        "CHK-CLA-LIVE-ACTIONS",
        "CHK-CLA-LIVE-BUS",
        "CHK-CLA-LIVE-MATCH",
        "CHK-CLA-LIVE-NODE",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_live_bus_test_seq("cla_live_bus_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLA_LIVE_BUS_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"mux {seq.sampled_mux}, states {[hex(v) for v in seq.states]}, "
                f"{seq.action_values} action writes, counters {seq.counter_after}, "
                f"node after move {seq.node_after_move}"
            ),
        )
