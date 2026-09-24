# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA transfers with the read and write channels decoupled, and two queued.

Sets CONFIG.DECOUPLE_RW from the mask the generated header gives it, runs a
scatter whose write side is the fragmented channel and a gather whose read side
is, comparing every row against its source, then programs and submits a second
descriptor without waiting for the first and requires both to complete with
their own payload. Nine 128-row 2D transfers then run into a SYS_OUT responder
holding READY low on the read side, the write side and both -- coupled,
decoupled, and with DECOUPLE_AW -- with the stall counted at the boundary and
every row compared. Two rows that cross a 4 KB page on one side only follow,
then an unaligned row, a descriptor queued behind a stalled transfer, and
writes to the read-triggered NEXT_ID registers.
CONFIG is restored to its reset and read back.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dma_decouple_rw_test_seq import smc_dma_decouple_rw_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. CSR accesses only; the row
# seeding and the readbacks go through the JTAG agent.
#
# Eighteen descriptors, at least 16 SEP_IN AXI accesses each: the CONFIG write,
# twelve descriptor writes, the NEXT_ID read that submits it, and at least one
# DONE poll.
DMA_DECOUPLE_RW_MIN_CSR_ACCESSES = 18 * 16


@pyuvm.test()
class smc_dma_decouple_rw_test(smc_base_test):
    """Run decoupled read/write DMA transfers and two queued descriptors."""

    required_evidence = (
        "CHK-DMA-DECOUPLE-RW",
        "CHK-DMA-LEGALIZER-BACKPRESSURE",
        "CHK-DMA-PAGE-SPLIT",
        "CHK-DMA-QUEUED-DESCRIPTORS",
        "CHK-DMA-UNALIGNED-QUEUED",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_decouple_rw_test_seq("smc_dma_decouple_rw_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            min_csr_accesses=DMA_DECOUPLE_RW_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.decoupled_transfers} decoupled transfers, {seq.queued} queued "
                f"descriptors, {len(seq.backpressured)} backpressured transfers, "
                f"{seq.rows_checked} rows compared"
            ),
        )
