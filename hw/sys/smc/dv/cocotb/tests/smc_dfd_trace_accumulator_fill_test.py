# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fill the DST trace packetizer accumulator from the SMC debug bus.

Holds the DFD clock on, puts every debug-bus mux into normal debug mode, opens
the trace funnel and RAM sink, enables the DST uncompressed, and drives the CLA
action field over its whole range until the DUT reports through
`Trdstcontrol.Trdstempty` that the packetizer holds trace data and through
`Trdstramwplow` that the sink has taken a filled bank.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_trace_accumulator_fill_test_seq import (
    smc_dfd_trace_accumulator_fill_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Bounded polls can add reads,
# never remove them, so this is the count with every poll satisfied first time.
#
#   DEBUG_CTRL force_clk_en write + readback                                  2
#   idle witness: Trdstcontrol read, Trdstramwplow read                       2
#   64 values of the 6-bit Dbmid field, normal debug mode                    64
#   sink: 4 window writes, Trdstramcontrol write + readback                   6
#   funnel: Trfunnelcontrol write + readback                                  2
#   DST Trdstcontrol enable write + readback                                  2
#   CLA arm: EAP reset write, CDbgClaCtrlStatus write, then per LogicalOp
#     value a configuration write and a CDbgEapStatus read until one
#     activates                                                               4
#   64 values of the 6-bit Action0 field, each a write and one status read   128
#   hand-off: the Trdstramwplow read that shows it off its reset              1
#   restore: EAP, CLA control, Trdstcontrol, Trfunnelcontrol,
#     Trdstramcontrol, DEBUG_BUS_MUX, DEBUG_CTRL                              7
#                                                                         ------
#                                                                            218
TRACE_ACCUMULATOR_MIN_CSR_ACCESSES = 218


@pyuvm.test()
class smc_dfd_trace_accumulator_fill_test(smc_base_test):
    """Drive debug-bus trace into the DST packetizer and watch it fill and drain."""

    required_evidence = (
        "CHK-DST-TRACE-ACCUMULATE",
        "CHK-DST-TRACE-BANK-HANDOFF",
        "CHK-DST-TRACE-IDLE",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_accumulator_fill_test_seq("trace_accumulator_fill_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_ACCUMULATOR_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.dbmids_programmed} debug-bus mux ids in normal debug mode, "
                f"{seq.actions_accumulating} of {seq.actions_swept} action values "
                f"accumulated, sink pointer 0x{seq.sink_pointer:08x}"
            ),
        )
