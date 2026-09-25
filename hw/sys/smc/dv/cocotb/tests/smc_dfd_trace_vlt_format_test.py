# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the DST trace path in the XOR plus VLT compression format, on a payload that moves.

The packetizer keeps a partial bank once a mode has run and the register
interface offers no flush, so the only empty packetizer this bench provides is
the one a run starts with and each compression mode gets its own leaf. This one
drives `Trdstformat` = 3, rotates the debug-bus mux segment selects while
the trace is live so consecutive samples differ, and changes the frame length
part way through.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_trace_format_sweep_test_seq import (
    FORMAT_XOR_VLT,
    smc_dfd_trace_format_sweep_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Bounded polls and the
# sampled-mux discovery can add accesses, never remove them, so this is the count
# with every poll and discovery satisfied first time.
#
#   DEBUG_CTRL force_clk_en write + readback                                  2
#   the initial segment-select programming, one write per mux id             64
#   funnel Trfunnelcontrol write + readback                                   2
#   sink: off write, 6 window writes, enable write + readback                 9
#   the first frame-length write + readback                                   2
#   Trdstcontrol write + readback                                             2
#   empty start: the packetizer read and the sink pointer read                2
#   CLA arm: EAP reset write, control write, 2 for the LogicalOp discovery    4
#   64 CLA mux writes, normal debug mode                                     64
#   sampled-mux discovery: 64 identifier-mode writes, the two-word
#     snapshot, one probe (write and two-word snapshot)                      69
#   64 action writes                                                         64
#   4 segment rotations of the sampled mux (write and two-word snapshot)     12
#   1 further frame-length write + readback                                   2
#   the quiesce write and the delivered read                                  2
#   restore: Trdstcontrol, Trdstimpl, EAP, CLA control, CLA mux, funnel,
#     sink control, DEBUG_BUS_MUX, DEBUG_CTRL                                 9
#                                                                         ------
#                                                                            309
TRACE_FORMAT_MIN_CSR_ACCESSES = 309


@pyuvm.test()
class smc_dfd_trace_vlt_format_test(smc_base_test):
    """Run the trace path in the XOR plus VLT compression format from an empty start."""

    required_evidence = (
        "CHK-DST-FORMAT-FRAMELEN",
        "CHK-DST-FORMAT-IDLE",
        "CHK-DST-FORMAT-PAYLOAD",
        "CHK-DST-FORMAT-STREAM",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_format_sweep_test_seq("trace_format_vlt_seq", fmt=FORMAT_XOR_VLT)
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_FORMAT_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"Trdstformat={seq.fmt}, sink pointer 0x{seq.baseline:08x} -> "
                f"0x{seq.delivered:08x}, segment selects {seq.rotations}, frame "
                f"lengths {sorted(set(seq.frame_lengths))}"
            ),
        )
