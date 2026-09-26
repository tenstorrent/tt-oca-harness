# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk sink-mode and stop writes across the DST flush and the memory write-out.

Measures the start, stop and neutral values of the CLA action field, walks the
stop action across the flush a memory-mode arm causes under three frame
lengths, and, once per cool reset, walks a memory-mode switch and back across
the fill and read-out of the first frame of a freshly started trace.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_dfd_trace_writeout_phase_test_seq import smc_dfd_trace_writeout_phase_test_seq
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
#   start search: 64 x (DST off, action, DST on, 2 pointer reads)            320
#   stop search: 64 x (start action, action, 2 pointer reads)                256
#   flush phases: 3 frame lengths x (Trdstimpl write, 16 x (2 sink arms and
#     4 action writes)), then a sink arm and a control read                  778
#   write-out phases: 64 x (DEBUG_CTRL, funnel, Trdstimpl, a sink arm, DST
#     enable, CLA control, start action, 2 sink control writes, mode read)   960
#   CurrentNode read, restart action, 2 pointer reads                          4
#   restore: 9 registers                                                       9
#                                                                         ------
#                                                                           2405
TRACE_WRITEOUT_PHASE_MIN_CSR_ACCESSES = 2405


@pyuvm.test()
class smc_dfd_trace_writeout_phase_test(smc_base_test):
    """Walk sink-mode and stop writes across the flush and write-out windows."""

    required_evidence = (
        "CHK-DST-PHASE-ACTIONS",
        "CHK-DST-PHASE-FLUSH",
        "CHK-DST-PHASE-WRITEOUT",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_writeout_phase_test_seq("trace_writeout_phase_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_WRITEOUT_PHASE_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"starts {seq.starts}, stops {seq.stops}, neutral {seq.neutral_action}, "
                f"{seq.stop_attempts} flush attempts, {seq.writeout_attempts} write-out attempts"
            ),
        )
