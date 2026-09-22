# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS XVISOR_REMAP full sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_xvisor_remap_test_seq import EXPECTED_ACCESSES, smc_xvisor_remap_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_xvisor_remap_test(smc_base_test):
    """Hypervisor remap table (0xC001_4000) sweep."""

    required_evidence = (
        "CHK-XVISOR-REMAP-CORESIDENT",
        "CHK-XVISOR-REMAP-RESET-DEFAULT",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_xvisor_remap_test_seq("smc_xvisor_remap_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            # Directed stimulus floor: 8 reset reads plus the 32 co-resident
            # pattern/restore accesses over XVISOR_REMAP 0..7. A constant of the
            # sequence module, not read back from `seq.accesses`.
            min_csr_accesses=EXPECTED_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="XVISOR_REMAP 0..7 reset sweep and co-resident per-entry patterns",
        )
