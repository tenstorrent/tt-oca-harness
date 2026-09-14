# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS OCTS sideband bounded VIP test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_avsbus_status_depth_test_seq import smc_avsbus_status_depth_test_seq
from seq_lib.smc_sideband_vip_utils import check_sideband_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_octs_sanity_test(smc_base_test):
    """Run sideband status decode as the public OCTS bounded checker."""

    required_evidence = ("CHK-SIDEBAND-OBSERVABILITY",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_status_depth_test_seq("smc_octs_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_sideband_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Directed stimulus floor: 5 SEP_IN AXI AVS status/config CSR
            # accesses. Written out here, not read from `seq.accesses`: a floor
            # that shrinks with the sequence cannot catch a sequence that
            # silently stops short.
            min_csr_accesses=5,
            csr_accesses=seq.accesses,
            proxy=True,
            details=(
                "SUBSTITUTE: AVS status CSR path, not pad OCTS BFM "
                "(real OCTS = smc_octs_dual_sync_test)"
            ),
        )
