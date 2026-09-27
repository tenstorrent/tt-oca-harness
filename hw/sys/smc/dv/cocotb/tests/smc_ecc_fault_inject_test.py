# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-1 / P2-7 ECC SBE/DBE inject on scratch bank0."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_ecc_fault_inject_test_seq import smc_ecc_fault_inject_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ecc_fault_inject_test(smc_base_test):
    """SBE inject fires during scratch FW boot; inject clear recovers."""

    required_evidence = (
        "CHK-ECC-INJECT",
        "CHK-ECC-INJECT-NO-DUT-SECDED",
        "CHK-ECC-INJECT-RECOVERY",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ecc_fault_inject_test_seq("ecc_fault_inject_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: 7 SEP_IN AXI scratch-inject/fetch
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=7,
            csr_accesses=seq.accesses,
            proxy=False,
            details=("DUT scratch0_inject_fire scored via live scratch fetch (SBE/recovery/DBE)"),
        )
