# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Gate the trace stream at the funnel, then let it through into two sink windows.

Runs the deny leg first, with the DST half of `Trfunneldisinput` set, because
the sink's wrap flag is hardware-set and sticky; then clears the field and
requires the same stimulus to reach the sink, and repeats into a second,
smaller window.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_trace_sink_window_test_seq import smc_dfd_trace_sink_window_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Bounded polls can add reads,
# never remove them, so this is the count with every poll satisfied first time.
#
#   DEBUG_CTRL force_clk_en write + readback                                  2
#   64 values of the 6-bit Dbmid field, normal debug mode                    64
#   sink armed for the deny leg: off write, 5 window writes, enable
#     write + readback                                                        8
#   funnel for the deny leg: control write + readback, disinput write
#     + readback                                                              4
#   DST enable write + readback                                               2
#   the pre-stimulus pointer read                                             1
#   CLA arm: EAP reset write, control write, 2 for the LogicalOp discovery    4
#   deny leg: 64 action writes, then the pointer read                        65
#   funnel for the allow leg: control write + readback, disinput write
#     + readback                                                              4
#   allow leg: 64 action writes, then the pointer read                       65
#   second window: 8 to re-arm the sink, 64 action writes, the pointer read  73
#   restore: DST, EAP, CLA control, disinput, funnel control, sink control,
#     DEBUG_BUS_MUX, DEBUG_CTRL                                               8
#                                                                         ------
#                                                                            300
TRACE_SINK_WINDOW_MIN_CSR_ACCESSES = 300


@pyuvm.test()
class smc_dfd_trace_sink_window_test(smc_base_test):
    """Block the trace at the funnel, release it, and take it into two windows."""

    required_evidence = (
        "CHK-DST-FUNNEL-ALLOW",
        "CHK-DST-FUNNEL-DENY",
        "CHK-DST-SINK-WINDOW",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_sink_window_test_seq("trace_sink_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_SINK_WINDOW_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"denied pointer 0x{seq.denied_pointer:08x}, allowed 0x"
                f"{seq.allowed_pointer:08x}, windows "
                + ", ".join(f"0x{w:x}" for w in sorted(seq.windows_taken))
            ),
        )
