# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read the trace sink out through its MMR port while the trace is still writing it.

The readout leaf stops the trace before reading the sink back, so the sink's
read and write sides never move together. This one keeps the trace running and
drives the read pointer and the RAM data port underneath it, in both values of
the sink's destination-mode field.
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
# sequence that silently stopped issuing accesses. No polling, every leg
# directed.
#
#   DEBUG_CTRL force_clk_en write + readback                                  2
#   64 mux identifiers in normal debug mode                                  64
#   funnel control write + readback                                           2
#   2 sink arms x (off write, 6 window writes, enable write + readback)      18
#   baseline: the data-port read and the write-pointer read                   2
#   DST enable write + readback                                               2
#   CLA arm: EAP reset write, control write, and 2 for the LogicalOp
#     discovery if the first value it tries activates                         4
#   2 live phases x (64 action writes, a seek write, a data read and a
#     write-pointer read at 8 of them, and the quiesce write)                178
#   restore: DST, EAP, CLA control, funnel, sink control, DEBUG_BUS_MUX,
#     DEBUG_CTRL                                                              7
#                                                                         ------
#                                                                            277
TRACE_SINK_CONCURRENT_MIN_CSR_ACCESSES = 277


@pyuvm.test()
class smc_dfd_trace_sink_concurrent_test(smc_base_test):
    """Drive the sink's read side while the trace is still writing into it."""

    required_evidence = (
        "CHK-DST-CONCURRENT-DRAIN",
        "CHK-DST-CONCURRENT-IDLE",
        "CHK-DST-CONCURRENT-MODE",
    )
    min_evidence = 3

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
