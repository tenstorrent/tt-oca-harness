# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLA event-action-pair sweep over the four nodes of the SMC CLA.

Arms the CLA, drives each of the 16 event-action pairs over the whole range of
its ``LogicalOp`` field while its own node is current, requires the hardware to
set that pair's ``CDbgEapStatus`` bit and the pair's own W2C bit to clear it,
and walks ``CurrentNode`` across all four nodes through the ``DestNode`` field.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_cla_node_eap_sweep_test_seq import smc_dfd_cla_node_eap_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Bounded polls can add reads,
# never remove them, so this is the count with every poll satisfied first time.
#
#   reset status read                                                         1
#   16 EAP registers written to their RDL reset before arming                16
#   arm CDbgClaCtrlStatus + readback                                          2
#   4 nodes x (CurrentNode read + 4 pairs x 4 LogicalOp values x
#     (configuration write + status read + quiet write))                    196
#   one W2C clear per pair: set, release, readback                           48
#   3 node moves x (destination write + CurrentNode read + quiet write +
#     W2C set, release, readback)                                            18
#   16 EAP registers restored, CDbgClaCtrlStatus restored, final status read 18
#                                                                         ------
#                                                                            299
CLA_NODE_EAP_MIN_CSR_ACCESSES = 299


@pyuvm.test()
class smc_dfd_cla_node_eap_sweep_test(smc_base_test):
    """Activate every EAP of every CLA node and clear it through its W2C bit."""

    required_evidence = (
        "CHK-CLA-EAP-LOGICAL-OP-FIRE",
        "CHK-CLA-EAP-STATUS-RESET",
        "CHK-CLA-EAP-STATUS-W2C",
        "CHK-CLA-NODE-TRAVERSAL",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_node_eap_sweep_test_seq("cla_node_eap_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLA_NODE_EAP_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.pairs_activated} EAP pairs activated and {seq.pairs_cleared} status "
                f"bits cleared across nodes {seq.nodes_visited}"
            ),
        )
