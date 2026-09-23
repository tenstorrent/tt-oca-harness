# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the DST trace path in each compression format its RDL publishes.

Walks `Trdstformat` over the three values the field's own RDL description
names, with a timestamp injected and the CLA action bus moving so the payload
changes between samples, and measures what each mode put into the trace RAM
sink from a write pointer this sequence had put back to zero.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_trace_format_sweep_test_seq import smc_dfd_trace_format_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Bounded polls can add reads,
# never remove them, so this is the count with every poll satisfied first time.
#
#   DEBUG_CTRL force_clk_en write + readback                                  2
#   64 values of the 6-bit Dbmid field, normal debug mode                    64
#   funnel Trfunnelcontrol write + readback                                   2
#   3 formats x (DST off write, sink off write, 5 window writes, the
#     re-armed pointer read, sink enable write + readback, the idle read,
#     DST start write + readback, EAP reset write, CLA arm write, 2 for the
#     shortest LogicalOp discovery, 64 action writes each with one status
#     read, and the pointer read that ends the mode) = 3 x 145              435
#   restore: DST, EAP, CLA control, funnel, sink control, DEBUG_BUS_MUX,
#     DEBUG_CTRL                                                              7
#                                                                         ------
#                                                                            510
TRACE_FORMAT_SWEEP_MIN_CSR_ACCESSES = 510


@pyuvm.test()
class smc_dfd_trace_format_sweep_test(smc_base_test):
    """Drive the trace path in each published format and compare what reaches the sink."""

    required_evidence = (
        "CHK-DST-FORMAT-IDLE",
        "CHK-DST-FORMAT-STREAM",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_format_sweep_test_seq("trace_format_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_FORMAT_SWEEP_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                "sink pointers "
                + ", ".join(f"Trdstformat={f}:0x{v:x}" for f, v in sorted(seq.pointers.items()))
                + f"; accumulating action values {dict(sorted(seq.accumulated.items()))}"
            ),
        )
