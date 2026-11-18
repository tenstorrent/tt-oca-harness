# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The DFD clock gate seen through register accesses, and the CLA enable and lock.

With `cg_en` 1 and `force_clk_en` 0 a CLA and a DST register access answer
SLVERR with 0xBADCAB1E and a write leaves the word; with `force_clk_en` 1 and
with `cg_en` 0 the same accesses answer OKAY. With `DEBUG_CTRL` 0 the CLA
evaluates and its timestamp advances, and the force changes nothing. With
`EnableCla` 0 a pair whose relation is made true stays clear; after `ClaLock`
a write of `EnableCla` 0 reads back 1 and the pair still sets its status.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_clock_gate_access_test_seq import smc_dfd_clock_gate_access_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every discovery loop and poll
# is counted at one iteration, the shortest each can finish in.
#
#   gated access: 4 x (DEBUG_CTRL write + readback), the open Scratch write
#     and read and the Trdstimpl read, the 3 gated accesses, the 4 forced
#     accesses, the reopened read and clear                                  20
#   unforced clock: EAP reset, CLA arm, one relation try (write, status
#     read), 2 timestamp reads, DEBUG_CTRL write + readback, the quiet
#     write, 2 W2C writes, 8 status reads, the arm, one status poll, 2
#     timestamp reads, DEBUG_CTRL write + readback                           25
#   enable gate: quiet write, 2 W2C writes, 8 status reads, counter and
#     timestamp reads, CLA control, arm, 8 status reads, counter and
#     timestamp reads, CLA control, one status poll, quiet write, 2 W2C
#     writes, the lock write, CLA control, its readback, arm, one poll       36
#                                                                         ------
#                                                                            81
CLOCK_GATE_MIN_CSR_ACCESSES = 81


@pyuvm.test()
class smc_dfd_clock_gate_access_test(smc_base_test):
    """Gate the DFD clock around CLA and DST accesses, then gate the CLA by its enable."""

    required_evidence = (
        "CHK-CLA-ENABLE-CLA-GATES",
        "CHK-DFD-CG-EN-GATED-ACCESS",
        "CHK-DFD-CLOCK-RUNS-UNFORCED",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_clock_gate_access_test_seq("clock_gate_access_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLOCK_GATE_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"responses {seq.responses}, timestamps "
                f"{[(label, hex(word)) for label, word in seq.timestamps]}, "
                f"{seq.value_checks} value checks"
            ),
        )
