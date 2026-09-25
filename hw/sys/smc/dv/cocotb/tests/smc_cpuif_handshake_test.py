# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every register block's AXI-Lite front end, pipelined, skewed and backpressured.

On a side-effect-free probe register in each of 24 register blocks: an
outstanding group of interleaved reads and writes deep enough that an accept
meets an acknowledge on both sides, a write with W ahead of AW (and on cpu_ctrl
and zeroer_ctrl one with AW ahead of W), and sixteen writes and sixteen reads
outstanding against a held BREADY and RREADY. Every write carries back the value the probe held;
every read must return it, and the probe must still hold it afterwards.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpuif_handshake_test_seq import smc_cpuif_handshake_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 23 blocks with a read side -- the 21 probes, straps and uart_16550_dl -- at 41
# SEP_IN AXI accesses each: the held read, a pipelined group of three reads and
# three writes, the W-first write, sixteen writes against a held BREADY and
# sixteen reads against a held RREADY, and the closing read; then 78 more: twelve
# write-write-read groups (36), twelve write-read groups (24), eight writes and a
# read against a held BREADY (9) and eight reads and a write against a held
# RREADY (9). On top of those:
# the AW-first write on cpu_ctrl and zeroer_ctrl (2), the LCR read, DLAB write,
# restore write and restore read around uart_16550_dl (4), and
# uart_16550_main_wo's three pipelined writes, W-first write and sixteen
# BREADY-held writes with the IIR read after them (21).
CPUIF_HANDSHAKE_MIN_CSR_ACCESSES = 23 * (41 + 78) + 2 + 4 + 21


@pyuvm.test()
class smc_cpuif_handshake_test(smc_base_test):
    """Pipeline, skew and backpressure every register block's front end."""

    required_evidence = (
        "CHK-CPUIF-PIPELINED",
        "CHK-CPUIF-READY-BACKPRESSURE",
        "CHK-CPUIF-WRITE-SKEW",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpuif_handshake_test_seq("smc_cpuif_handshake_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=CPUIF_HANDSHAKE_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{seq.blocks} register blocks, {seq.groups} timed groups",
        )
