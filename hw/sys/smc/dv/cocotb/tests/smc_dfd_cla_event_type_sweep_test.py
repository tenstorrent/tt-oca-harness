# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the CLA event selectors of one node over every event index.

Drives `EventType0`, `EventType1` and `EventType2` over all 64 values of their
fields on each of node 0's four event-action pairs, with the relation left at
its RDL reset so a pair activates only when the selected event is asserted,
and reads `CDbgEapStatus` after every value.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_cla_event_type_sweep_test_seq import smc_dfd_cla_event_type_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. An activation adds a quiesce
# write and three W2C accesses, so this is the count with none observed.
#
#   DEBUG_CTRL force_clk_en write                                             1
#   64 values of the 6-bit Dbmid field, normal debug mode                    64
#   CDbgEapStatus reset read                                                  1
#   CLA arm: 4 pair reset writes, the control write, the CurrentNode read      6
#   3 selectors x 4 pairs x 64 values x (write, readback, status read)      2304
#   4 per-pair quiesce writes per selector                                   12
#   restore: 4 pairs, CLA control, DEBUG_BUS_MUX, DEBUG_CTRL                  7
#                                                                         ------
#                                                                           2395
CLA_EVENT_TYPE_MIN_CSR_ACCESSES = 2395


@pyuvm.test()
class smc_dfd_cla_event_type_sweep_test(smc_base_test):
    """Drive every event index into every event selector of node 0's pairs."""

    required_evidence = (
        "CHK-CLA-EVENT-SELECT-LIVE",
        "CHK-CLA-EVENT-SELECT-SWEEP",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_event_type_sweep_test_seq("cla_event_type_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLA_EVENT_TYPE_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.selector_values} selector values driven, live event indices "
                + ", ".join(f"{name}:{sorted(v)}" for name, v in seq.live_events.items() if v)
            ),
        )
