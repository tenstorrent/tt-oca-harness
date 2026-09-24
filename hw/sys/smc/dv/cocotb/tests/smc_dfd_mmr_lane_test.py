# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte-write the DST and DST-sink MMRs and touch an unmapped offset of each block.

Writes the low byte of 18 registers of the `dst` and `dst_sink` sub-blocks
one byte at a time and requires no other byte to move, then reads and writes
one offset inside each block's register hole and requires the neighbouring
registers to hold.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_mmr_lane_test_seq import smc_dfd_mmr_lane_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. No polling, every leg
# directed.
#
#   18 registers x (the before read, the byte write, the read after it, the
#     whole write-back and its readback)                                     90
#   2 blocks x (2 neighbour reads, the hole read, the hole write, 2
#     neighbour reads)                                                       12
#                                                                         ------
#                                                                            102
MMR_LANE_MIN_CSR_ACCESSES = 102


@pyuvm.test()
class smc_dfd_mmr_lane_test(smc_base_test):
    """Byte-write every DST and sink MMR, and touch each block's unmapped offset."""

    required_evidence = (
        "CHK-DFD-MMR-BYTE",
        "CHK-DFD-MMR-UNMAPPED",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_mmr_lane_test_seq("mmr_lane_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=MMR_LANE_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.byte_written} byte writes ({seq.byte_dropped} ignored, "
                f"{seq.byte_taken} taken), unmapped {seq.unmapped}"
            ),
        )
