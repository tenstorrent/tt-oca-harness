# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cool-reset the SMC while the DST is tracing and check the DFD returns to reset.

Programs the trace path, starts the uncompressed trace from a measured action,
pulses the public cool reset, and checks that the DFD registers read their RDL
reset values, the sink write pointer is back at its reset value, and the trace
starts again once the path is programmed afresh.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_dfd_trace_reset_test_seq import smc_dfd_trace_reset_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every discovery loop and poll
# is counted at one iteration, the shortest each can finish in.
#
#   bring-up: DEBUG_CTRL write + readback, 64 DEBUG_BUS_MUX writes, funnel
#     write + readback, a six-write sink arm, the DST enable                  75
#   CLA arm write and one relation try (write, status read)                    3
#   64 CLA mux writes                                                         64
#   start search, one try: DST off, action, DST on, 2 pointer reads            5
#   Trdstimpl write + readback, 9 register reads, 2 pointer reads             13
#   after the reset: 9 register reads, 2 pointer reads                        11
#   bring-up, CLA arm and CLA mux again, start action, 2 pointer reads       145
#   restore: 9 registers                                                       9
#                                                                         ------
#                                                                            325
TRACE_RESET_MIN_CSR_ACCESSES = 325


@pyuvm.test()
class smc_dfd_trace_reset_test(smc_base_test):
    """Cool-reset the SMC with the DST tracing and check the DFD registers and trace."""

    required_evidence = (
        "CHK-DFD-RESET-CLEARED",
        "CHK-DFD-RESET-LIVE",
        "CHK-DFD-RESET-RESTART",
        "CHK-DFD-RESET-TAKEN",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_trace_reset_test_seq("trace_reset_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=TRACE_RESET_MIN_CSR_ACCESSES,
            proxy=False,
            details=f"start action {seq.start_action}, checked {seq.checked_registers}",
        )
