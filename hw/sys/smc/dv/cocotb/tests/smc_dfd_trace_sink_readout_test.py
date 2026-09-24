# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read the captured trace back out of the sink RAM and cycle the sink's modes.

Records an all-zero baseline from the sink RAM data port before any trace runs,
captures a trace, walks `Trdstramrplow` across the window reading `Trdstramdata`
at each position, then runs the sink at both values of `Trdstrammode` and takes
`Trdstramactive` from 1 to 0 with the sink still enabled.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_trace_sink_readout_test_seq import smc_dfd_trace_sink_readout_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   DEBUG_CTRL force_clk_en write + readback                                  2
#   64 values of the 6-bit Dbmid field, normal debug mode                    64
#   funnel control write + readback                                           2
#   sink armed for the baseline: off write, 6 window writes, enable
#     write + readback                                                        9
#   baseline: the seek write, its readback, the data read                     3
#   DST enable write + readback                                               2
#   CLA arm: EAP reset write, control write, 2 for the LogicalOp discovery    4
#   fill: 64 action writes and the wrap-flag read, one sweep at least        65
#   read-out: 16 positions x (seek write, seek readback, data read), plus
#     the same three on the window's last word                               51
#   2 sink modes x (9 to re-arm the sink, 64 action writes)                 146
#   deactivation: the active read, the write and its readback                 3
#   restore: DST, EAP, CLA control, funnel, sink control, DEBUG_BUS_MUX,
#     DEBUG_CTRL                                                              7
#                                                                         ------
#                                                                            358
TRACE_SINK_READOUT_MIN_CSR_ACCESSES = 358


@pyuvm.test()
class smc_dfd_trace_sink_readout_test(smc_base_test):
    """Fill the sink, read the trace back out of it, and cycle its mode and enables."""

    required_evidence = (
        "CHK-DST-SINK-BASELINE",
        "CHK-DST-SINK-DEACTIVATE",
        "CHK-DST-SINK-MODE",
        "CHK-DST-SINK-READOUT",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_sink_readout_test_seq("trace_sink_readout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_SINK_READOUT_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.nonzero_words} of {seq.words_read} words non-zero against baseline "
                f"0x{seq.baseline:08x}, modes {sorted(set(seq.modes_programmed))}"
            ),
        )
