# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FLR edges inside a running cool-reset sequence give one pulse of the single-request width.

Source: ``hw/sys/smc/doc/clk_rst.adoc`` "Timing and Recovery".
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_flr_hold_edge_requeue_test_seq import smc_flr_hold_edge_requeue_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   idle reads of ISOLATE_REQ_PINEN_REG and ISOLATE_REQ_SMC_REG              2
#   one counter programming: two writes and two readbacks                    4
#   two latch clears, each a write and at least one readback                 4
#   both counters cleared and read back                                      4
FLR_HOLD_EDGE_REQUEUE_MIN_CSR_ACCESSES = 14


@pyuvm.test()
class smc_flr_hold_edge_requeue_test(smc_base_test):
    """One arm request, then a request with edges inside the count and inside the hold."""

    required_evidence = ("CHK-FLR-NO-REQUEUE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_flr_hold_edge_requeue_test_seq("smc_flr_hold_edge_requeue_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=FLR_HOLD_EDGE_REQUEUE_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{len(seq.rows)} FLR legs sampled on clk_ref_i",
        )
