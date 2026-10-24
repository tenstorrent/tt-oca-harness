# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive the CLA's signal event generators, counters and action outputs on a moving bus.

Gives the CLA a debug bus that moves between two measured states, programs the
edge, change, transition, comparator and LFSR generators from them, drives the
action field with the cross-trigger stretch, clock halt and counter reset on
target enabled, sweeps the actions again with the lowest clock-halt mask bit
set, takes the CLA mux through fine-grain normal mode into identifier mode,
moves the node chain away from pairs whose relation holds, then writes and
reads back every field of the CLA mux select register and puts it in toggle
mode. With the CLA back at its reset, the toggle-mode bus is then traced
uncompressed into the trace sink until it wraps the 16 KiB of the eight trace
RAMs, and every stored word is read back through Trdstramdata.
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
#   the halt-mask sweep: DEBUG_CTRL write + readback, 64 action writes,
#     DEBUG_CTRL write + readback                                            68
#   2 custom-action enables and Resync, each write + readback                 6
#   CLA mux modes: 2 x (64 mode writes and the two-word snapshot), then
#     64 writes back to normal mode                                         196
#   leaving the node: one relation try (write, status read), 3 destination
#     writes, the move write and one CurrentNode read                         7
#   CDbgMuxSelLo fields: 2 x (write and readback)                            4
#   toggle mode: write and readback, 16 two-word snapshots                  34
#   restore: 4 pairs, 4 counters, 14 named registers, 8 comparator
#     registers, DEBUG_BUS_MUX, DEBUG_CTRL                                   32
#   trace toggle set-up: CDbgMuxSelLo write and readback, Trdstcontrol
#     read, write and readback                                                5
#   sink set-up: DEBUG_CTRL and funnel, each write + readback, the sink off
#     write, 6 window and pointer writes, the sink control write +
#     readback, the empty read                                               14
#   trace pair: the CLA control write, 2 CurrentNode reads, one relation
#     try (write, status read)                                                5
#   trace fill: DST enable write + readback, 64 action writes, one wrap
#     poll, the stop write, one empty poll, 2 write-pointer reads, the
#     sink control read                                                      72
#   read-out: read-pointer write + readback, 4096 data reads, 64
#     read-pointer samples                                                 4162
#   content: CDbgMuxSelLo and Trdstcontrol reads                              2
#   trace restore: CDbgMuxSelLo, Trdstcontrol, Trdstramcontrol and 8 sink
#     pointers, each write + readback, then 4 reset writes                   26
#                                                                         ------
#                                                                          5377
CLA_LIVE_BUS_MIN_CSR_ACCESSES = 5377


@pyuvm.test()
class smc_dfd_cla_live_bus_test(smc_base_test):
    """Program the CLA generators from a moving bus and drive its actions."""

    required_evidence = (
        "CHK-CLA-LIVE-ACTIONS",
        "CHK-CLA-LIVE-BUS",
        "CHK-CLA-LIVE-MATCH",
        "CHK-CLA-LIVE-MUXMODES",
        "CHK-CLA-LIVE-MUXSEL-FIELDS",
        "CHK-CLA-LIVE-NODE",
        "CHK-CLA-LIVE-TOGGLE-MODE",
        "CHK-CLA-TOGGLE-TRACE-DATA",
        "CHK-CLA-TOGGLE-UNCOMP-CFG",
        "CHK-CLA-TRACE-FILL",
        "CHK-CLA-TRACE-READ",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 13

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
                f"node after move {seq.node_after_move}, "
                f"CLA mux snapshots {[hex(v) for v in seq.mux_snapshots]}, "
                f"toggle-mode snapshots {[hex(v) for v in seq.toggle_snapshots]}, "
                f"trace node {seq.trace_node} op {seq.trace_op}, "
                f"{len(seq.wp_samples)} write-pointer samples, final WP 0x{seq.final_wp:x}, "
                f"{len(seq.trace_words)} trace words, {len(seq.rp_samples)} read-pointer samples"
            ),
        )
