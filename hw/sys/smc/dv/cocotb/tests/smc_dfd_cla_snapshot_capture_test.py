# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Make every CLA event-action pair capture a debug-signal snapshot.

Reads all 32 snapshot registers at their reset, then walks the node chain and
drives every pair's action field over its whole declared range with a relation
measured to activate that pair, and requires snapshot registers to leave their
reset.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_cla_snapshot_capture_test_seq import (
    smc_dfd_cla_snapshot_capture_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Bounded polls and the
# relation discovery can add accesses, never remove them, so this is the count
# with each discovery satisfied first time.
#
#   DEBUG_CTRL force_clk_en write                                             1
#   64 mux identifiers in normal debug mode                                  64
#   32 snapshot reset reads                                                  32
#   16 pair reset writes plus the CLA control write                          17
#   16 pairs x (2 for the relation discovery, 64 action writes, 2 snapshot
#     reads, the quiesce write)                                            1104
#   3 node moves x (destination write, the CurrentNode read, the quiesce
#     write)                                                                  9
#   restore: 16 pairs, CLA control, DEBUG_BUS_MUX, DEBUG_CTRL                19
#                                                                         ------
#                                                                           1246
CLA_SNAPSHOT_MIN_CSR_ACCESSES = 1246


@pyuvm.test()
class smc_dfd_cla_snapshot_capture_test(smc_base_test):
    """Drive every pair's action field so the snapshot registers are written."""

    required_evidence = (
        "CHK-CLA-SNAPSHOT-DRIVE",
        "CHK-CLA-SNAPSHOT-QUIESCENT",
        "CHK-CLA-SNAPSHOT-RESET",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_snapshot_capture_test_seq("cla_snapshot_capture_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLA_SNAPSHOT_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.pairs_driven} pairs driven across nodes {seq.nodes_visited}, "
                f"{len(seq.captured)} snapshot registers changed"
            ),
        )
