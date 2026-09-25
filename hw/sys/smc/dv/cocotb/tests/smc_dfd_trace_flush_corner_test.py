# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive the DST's trace control through stream lengths, action loops and sink flushes.

Measures which values of the CLA action field start, stop and leave alone the
trace, then uses them for start/stop streams, a stream-length drop under a
running trace, a two-node start/stop loop, timestamp-phase walks, frame-length
changes mid-frame and memory-mode sink arms under running traces.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_trace_flush_corner_test_seq import smc_dfd_trace_flush_corner_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every discovery loop and poll
# is counted at one iteration, the shortest each can finish in. A sink arm is
# six writes: control off, start, limit, write and read pointers, control on.
#
#   bring-up: DEBUG_CTRL write + readback, 64 DEBUG_BUS_MUX writes, funnel
#     write + readback, a sink arm, the DST enable                            75
#   CLA arm write and one relation try (write, status read)                    3
#   64 CLA mux writes                                                         64
#   sampled-mux discovery: 64 identifier-mode writes, the two-word
#     snapshot, one probe (write and two-word snapshot)                       69
#   8 stream-length encodings, each write + readback                          16
#   memory re-arms: 3 sink arms, 2 limit reads, the closing sink arm          26
#   held sink: control write, 2 disinput writes + readbacks, a sink arm       11
#   start search: 64 x (DST off, action, DST on, 2 pointer reads)            320
#   stop search: 64 x (start action, action, 2 pointer reads)                256
#   start/stop streams: Trdstimpl write + readback, then 4 sync values x
#     (quiet action, DST off, sink arm, DST on, one pair: 2 actions and a
#     pointer read)                                                           50
#   overrun: 4 sync values x (quiet action, DST off, Trdstimpl write +
#     readback, sink arm, DST on, start action, one poll, Trdstimpl write +
#     readback, 8 hold actions, 2 pointer reads), Trdstimpl restore write +
#     readback                                                               102
#   node loop: quiet action, DST off and on, 2 loop actions, park action,
#     CurrentNode read, 2 home actions, CurrentNode read, node 1 reset         11
#   timestamp phases: a sink arm, 32 x (DST on, start, stop), then
#     32 x (quiet action, DST off, DST on, start, DST off)                   262
#   frame toggles: closure write + readback, quiet action, DST off, a sink
#     arm, DST on, start action, 64 x 2 Trdstimpl writes, 2 pointer reads,
#     closure restore                                                        143
#   memory arms: a sink arm, DST on, start action, 24 neutral actions, 2
#     sink arms; then per loop of n nodes, 4 x (n loop actions, a sink arm,
#     3 park actions, 2 home actions, a sink arm) over loops of 3, 3, 4, 4,
#     4 and 2 nodes; 3 node resets, CurrentNode read, start action, 2
#     pointer reads                                                          539
#   restore: 9 registers                                                       9
#                                                                         ------
#                                                                           1956
TRACE_FLUSH_CORNER_MIN_CSR_ACCESSES = 1956


@pyuvm.test()
class smc_dfd_trace_flush_corner_test(smc_base_test):
    """Measure the trace actions and drive the DST's control corners with them."""

    required_evidence = (
        "CHK-DST-FLUSH-ACTIONS",
        "CHK-DST-FLUSH-LOOP",
        "CHK-DST-FLUSH-MEMARMS",
        "CHK-DST-FLUSH-PHASES",
        "CHK-DST-FLUSH-REGS",
        "CHK-DST-FLUSH-STREAMS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_flush_corner_test_seq("trace_flush_corner_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_FLUSH_CORNER_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"starts {seq.starts}, stops {seq.stops}, neutral {seq.neutral_action}, "
                f"stream pairs {seq.stream_pairs}, memory arms {seq.memory_arms}"
            ),
        )
