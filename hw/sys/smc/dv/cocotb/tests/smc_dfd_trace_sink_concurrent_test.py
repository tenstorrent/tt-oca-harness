# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read the trace sink out through its MMR port while the trace is still writing it.

The readout leaf stops the trace before reading the sink back, so the sink's
read and write sides never move together. This one keeps the trace running and
drives the read pointer and the RAM data port underneath it, in both values of
the sink's destination-mode field. Under a compressed stream it then switches
the traced bus between two states an odd number of bytes apart. It then stops
the trace twice, once by clearing the DST enable alone and once through the
sink's stop-on-wrap setting, walks the sync-mode field under a running
stream, and ends by running the trace into the sink's memory mode and
recovering in RAM mode.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_trace_sink_concurrent_test_seq import (
    smc_dfd_trace_sink_concurrent_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every poll and discovery
# loop (the window fill, the waits for the DST to empty, the sampled-mux and
# restart-action searches) is counted at one iteration, which is the shortest
# each can finish in.
#
#   DEBUG_CTRL force_clk_en write + readback                                  2
#   64 mux identifiers in normal debug mode                                  64
#   funnel control write + readback                                           2
#   5 sink arms x (off write, 6 window writes, enable write + readback)      45
#   baseline: the data-port read and the write-pointer read                   2
#   DST enable write + readback                                               2
#   CLA arm: EAP reset write, control write, and 2 for the LogicalOp
#     discovery if the first value it tries activates                         4
#   window fill: one sweep of 64 action writes and the write-pointer read    65
#   2 live phases x (64 action writes, a seek write, a data read and a
#     write-pointer read at 8 of them, and the quiesce write)                178
#   the shaped phase: the compressed-format write and its readback (2),
#     then per closure mode the frame-config write and its readback (2)
#     and per frame length a write, a readback and 4 action writes, so
#     2 x (2 + 16 x 6)                                                      198
#   odd offsets: long-frame write + readback, the EAP write, 64 CLA mux
#     writes, 64 identifier-mode writes, the two-word snapshot, one probe
#     (write and two-word snapshot), the emptying stop write + readback and
#     one empty poll, the restart write + readback, one restart try (action
#     write, two mux writes, the empty read), the two pointer reads around
#     160 mux writes, the closing two-word snapshot and 64 normal-mode
#     writes                                                                373
#   window above the RAM: a sink arm (9), DST control write + readback,
#     8 held action writes, one pointer poll, the start restore write        21
#   one-line window: DST control write + readback, a sink arm (9), the limit
#     read, 8 held writes                                                     20
#   memory mode: a sink arm (9), DST control write + readback, 100 held
#     action writes each followed by a bus switch, the empty read, the stop (sink control and DST control
#     writes + readbacks, 8 sink control reads, the restart write + readback),
#     a RAM-mode sink arm (9), 8 held action writes, one pointer poll, and
#     8 x (an action write and 4 data-port reads)                            284
#   software stop: long-frame write + readback, restart write + readback,
#     16 action writes, short-frame write + readback, 16 action writes, the
#     running read, the stop write + readback and one empty poll             42
#   frame mode off: frame config write + readback, run write + readback, 8
#     held action writes, stop write + readback, one empty poll              15
#   stop on wrap: DST enable write + readback, 8 x (16 action writes and a
#     write-pointer read), sink-disable write + readback, 4 action writes
#     and the closing write-pointer read                                    145
#   sync-mode walk: 2 timestamp sources x (impl write + readback, then
#     4 x (control write + readback, 8 action writes and 24 writes of the
#     held restarting action))                                               276
#   restore: DST control, DST impl, frame config, EAP, CLA control, CLA
#     mux, funnel, sink control, DEBUG_BUS_MUX, DEBUG_CTRL                   10
#                                                                         ------
#                                                                          1748
TRACE_SINK_CONCURRENT_MIN_CSR_ACCESSES = 1748


@pyuvm.test()
class smc_dfd_trace_sink_concurrent_test(smc_base_test):
    """Drive the sink's read side while the trace is still writing into it."""

    required_evidence = (
        "CHK-DST-CONCURRENT-DRAIN",
        "CHK-DST-CONCURRENT-EDGES",
        "CHK-DST-CONCURRENT-FRAMEWALK",
        "CHK-DST-CONCURRENT-HIGHSTART",
        "CHK-DST-CONCURRENT-IDLE",
        "CHK-DST-CONCURRENT-MEMORY",
        "CHK-DST-CONCURRENT-MODE",
        "CHK-DST-CONCURRENT-ODDBYTES",
        "CHK-DST-CONCURRENT-STOP",
        "CHK-DST-CONCURRENT-STOPWRAP",
        "CHK-DST-CONCURRENT-SYNCWALK",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_sink_concurrent_test_seq("trace_sink_concurrent_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_SINK_CONCURRENT_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.nonzero_words} of {seq.words_read} words non-zero, "
                f"{seq.positions_driven} read-pointer positions, sink modes "
                f"{sorted(set(seq.modes_live))}"
            ),
        )
